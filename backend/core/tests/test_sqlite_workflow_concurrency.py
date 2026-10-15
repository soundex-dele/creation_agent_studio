"""Run with testing_sqlite_service against an isolated worker-owned database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections

from apps.conversations.models import Conversation
from modules.execution.application.runs import append_event_and_transition, create_run
from modules.execution.models import Run
from modules.execution.runtime.builtin import _create_or_load_step_run


@pytest.mark.django_db(transaction=True)
def test_chat_node_creation_competes_with_events_without_duplicate_conversations():
    if connection.settings_dict['ENGINE'] != 'core.sqlite_service':
        pytest.skip('Requires the real SQLite data service integration profile')
    actor = get_user_model().objects.create_user(username='sqlite-workflow-concurrency')
    organization = actor.owned_organizations.get()
    root = create_run(
        organization=organization, owner=actor, executor_kind='workflow',
        executor_key='workflow-dag', source_type='workflow', source_id='concurrency',
        definition_snapshot={}, input_data={},
    )
    barrier = Barrier(3)

    def create_nodes():
        try:
            local_root = Run.objects.select_related('owner', 'organization').get(pk=root.id)
            barrier.wait(timeout=10)
            created = 0
            for index in range(8):
                _, new = _create_or_load_step_run(local_root, {
                    'id': f'step-{index}', 'key': f'step-{index}', 'name': f'Step {index}',
                    'executor_kind': 'agent', 'executor_key': 'agent-completion',
                    'content': {'kind': 'chat'},
                }, {}, {}, {})
                created += int(new)
            return created
        finally:
            connections.close_all()

    def append_progress():
        try:
            barrier.wait(timeout=10)
            for index in range(25):
                append_event_and_transition(
                    run_id=root.id, organization_id=organization.id,
                    event_type='progress.updated', payload={'current': index},
                )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(create_nodes)
        second = pool.submit(create_nodes)
        events = pool.submit(append_progress)
        assert first.result(timeout=30) + second.result(timeout=30) == 8
        events.result(timeout=30)

    assert root.child_runs.count() == 8
    assert Conversation.objects.filter(user=actor, process_id__startswith='workflow:step-').count() == 8
    assert list(root.events.order_by('sequence').values_list('sequence', flat=True)) == list(range(1, 27))
    assert not root.events.filter(type__in=['run.failed', 'run.retry_scheduled']).exists()

import pytest
from modules.execution.api.run_access import can_access_run, has_application_access_policy
from modules.execution.api.streaming import _load_event_batch, StreamAccessLost
from modules.execution.application.runs import create_run
from apps.enterprise.models import Membership
from .test_douyin import ctx  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def test_child_events_recheck_application_permission(ctx):
    child = create_run(organization=ctx.org, owner=ctx.owner, parent=ctx.task.run,
        executor_kind='agent', executor_key='agent-completion', source_type='application_step',
        source_id='child', node_key='child', definition_snapshot={}, input_data={})
    assert can_access_run(ctx.owner, child)
    assert has_application_access_policy(child)
    assert not can_access_run(ctx.reader, child)
    # Call the synchronous implementation on this test's database connection.
    assert isinstance(_load_event_batch.func(user=ctx.owner, organization_id=ctx.org.pk,
        run_id=child.pk, after=0, limit=10), list)
    ctx.app.is_active = False
    ctx.app.save(update_fields=['is_active'])
    assert not can_access_run(ctx.owner, child)
    with pytest.raises(StreamAccessLost):
        _load_event_batch.func(user=ctx.owner, organization_id=ctx.org.pk,
            run_id=child.pk, after=0, limit=10)


def test_member_revocation_removes_task_access(ctx):
    assert can_access_run(ctx.owner, ctx.task.run)
    Membership.objects.filter(organization=ctx.org, user=ctx.owner).update(is_active=False)
    assert not can_access_run(ctx.owner, ctx.task.run)


def test_signed_artifact_still_checks_current_application_access(ctx, settings, tmp_path):
    from modules.execution.models import RunArtifact
    from modules.execution.infrastructure.artifacts import artifact_token
    settings.ARTIFACT_ROOT = tmp_path
    (tmp_path / 'result.txt').write_text('private result', encoding='utf-8')
    artifact = RunArtifact.objects.create(organization=ctx.org, run=ctx.task.run,
        kind='file', object_key='result.txt', content_hash='a' * 64, mime_type='text/plain', size=14)
    url = f'/api/v1/organizations/{ctx.org.pk}/runs/{ctx.task.run_id}/artifacts/{artifact.pk}/content?token={artifact_token(artifact)}'
    response = ctx.client.get(url)
    assert response.status_code == 200
    response.close()
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url).status_code == 404
    ctx.client.force_authenticate(ctx.owner)
    ctx.app.is_active = False
    ctx.app.save(update_fields=['is_active'])
    assert ctx.client.get(url).status_code == 404

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.conversations.models import Conversation, Message
from apps.enterprise.management.commands.enforce_retention import Command
from modules.execution.application.runs import create_run
from modules.execution.models import IdempotencyRecord, Run, RunArtifact


pytestmark = pytest.mark.django_db


def _terminal_run(organization, owner, *, age_days=10, parent=None, node_key=""):
    run = create_run(
        organization=organization,
        owner=owner,
        executor_kind=Run.ExecutorKind.AGENT,
        executor_key="agent-completion",
        source_type="test",
        definition_snapshot={},
        input_data={},
        parent=parent,
        node_key=node_key,
    )
    finished_at = timezone.now() - timedelta(days=age_days)
    Run.objects.filter(pk=run.id).update(
        status=Run.Status.SUCCEEDED,
        finished_at=finished_at,
    )
    run.refresh_from_db()
    return run


def test_retention_deletes_expired_idempotency_records():
    owner = get_user_model().objects.create_user(username="retention-idempotency")
    organization = owner.owned_organizations.get()
    organization.governance_policy.retention_days = 365
    organization.governance_policy.save(update_fields=("retention_days",))
    expired = IdempotencyRecord.objects.create(
        organization=organization,
        actor=owner,
        operation="test",
        key="expired",
        request_fingerprint="a" * 64,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    active = IdempotencyRecord.objects.create(
        organization=organization,
        actor=owner,
        operation="test",
        key="active",
        request_fingerprint="b" * 64,
        expires_at=timezone.now() + timedelta(days=1),
    )

    Command()._cycle(dry_run=False)

    assert not IdempotencyRecord.objects.filter(pk=expired.pk).exists()
    assert IdempotencyRecord.objects.filter(pk=active.pk).exists()


def test_retention_deletes_old_terminal_run_and_artifact_after_database_delete(
    settings, tmp_path,
):
    settings.ARTIFACT_ROOT = tmp_path
    owner = get_user_model().objects.create_user(username="retention-runs")
    organization = owner.owned_organizations.get()
    policy = organization.governance_policy
    policy.retention_days = 5
    policy.save(update_fields=("retention_days",))
    deletable = _terminal_run(organization, owner)
    recent_child = _terminal_run(
        organization,
        owner,
        age_days=1,
        parent=deletable,
        node_key="child",
    )
    protected = _terminal_run(organization, owner)
    conversation = Conversation.objects.create(
        user=owner, organization=organization, title="active"
    )
    Message.objects.create(
        conversation=conversation,
        run=protected,
        role="assistant",
        content="keep this projection",
    )
    paths = {}
    for run, name in (
        (deletable, "delete.txt"),
        (recent_child, "delete-child.txt"),
        (protected, "keep.txt"),
    ):
        object_key = f"runs/{run.id}/{name}"
        path = tmp_path / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        RunArtifact.objects.create(
            organization=organization,
            run=run,
            kind="result",
            object_key=object_key,
            content_hash="c" * 64,
            mime_type="text/plain",
            size=path.stat().st_size,
        )
        paths[run.id] = path

    Command()._cycle(dry_run=False)

    assert not Run.objects.filter(pk=deletable.pk).exists()
    assert not paths[deletable.id].exists()
    assert not Run.objects.filter(pk=recent_child.pk).exists()
    assert not paths[recent_child.id].exists()
    assert Run.objects.filter(pk=protected.pk).exists()
    assert paths[protected.id].exists()


def test_retention_dry_run_does_not_mutate_database_or_artifacts(settings, tmp_path):
    settings.ARTIFACT_ROOT = tmp_path
    owner = get_user_model().objects.create_user(username="retention-dry-run")
    organization = owner.owned_organizations.get()
    policy = organization.governance_policy
    policy.retention_days = 5
    policy.save(update_fields=("retention_days",))
    run = _terminal_run(organization, owner)
    object_key = f"runs/{run.id}/dry-run.txt"
    path = tmp_path / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"keep")
    RunArtifact.objects.create(
        organization=organization,
        run=run,
        kind="result",
        object_key=object_key,
        content_hash="d" * 64,
        mime_type="text/plain",
        size=4,
    )

    total = Command()._cycle(dry_run=True)

    assert total >= 1
    assert Run.objects.filter(pk=run.pk).exists()
    assert path.exists()


def test_retention_compaction_uses_configured_window_and_batch(
    monkeypatch, settings,
):
    owner = get_user_model().objects.create_user(username="retention-compaction")
    organization = owner.owned_organizations.get()
    organization.governance_policy.retention_days = 365
    organization.governance_policy.save(update_fields=("retention_days",))
    settings.RUN_EVENT_RETENTION_DAYS = 17
    settings.RUN_EVENT_COMPACTION_BATCH_SIZE = 23
    calls = []

    def compact(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        "apps.enterprise.management.commands.enforce_retention.compact_eligible_runs",
        compact,
    )

    before = timezone.now()
    Command()._cycle(dry_run=False)
    after = timezone.now()

    organization_call = next(
        call for call in calls
        if call["organization_id"] == organization.id
    )
    assert organization_call["batch_size"] == 23
    expected_before = organization_call["before"] + timedelta(days=17)
    assert before <= expected_before <= after

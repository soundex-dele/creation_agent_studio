from datetime import timedelta
from pathlib import Path
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import (
    InvalidRunTransition,
    LeaseLost,
    OrganizationMismatch,
)
from modules.execution.application.runs import (
    LeaseFence,
    append_event_and_transition,
    create_run,
    fail_attempt,
    finish_attempt,
    record_artifact,
    suspend_attempt_for_input,
)
from modules.execution.application.reaper import (
    expire_waiting_inputs,
    reap_expired_leases,
)
from modules.execution.infrastructure.claim import claim_next_run, renew_lease
from modules.execution.infrastructure.coordinator_lock import (
    CoordinatorAlreadyRunning,
    CoordinatorFileLock,
)
from modules.execution.models import Run, RunAttempt, RunEvent, RunLease
from modules.tenancy.models import Membership, Organization


@pytest.fixture
def actor(db):
    return get_user_model().objects.create_user(
        username="v2-owner",
        email="owner@example.com",
        password="test-password",
    )


@pytest.fixture
def organization(actor):
    organization = Organization.objects.create(
        name="V2 Organization",
        slug="v2-organization",
        owner=actor,
    )
    Membership.objects.create(
        organization=organization,
        user=actor,
        role=Membership.Role.OWNER,
    )
    return organization


def _create_run(organization, actor, **overrides):
    values = {
        "organization": organization,
        "owner": actor,
        "executor_kind": Run.ExecutorKind.MEDIA,
        "source_type": "application",
        "source_id": "batch-transcribe",
        "definition_snapshot": {"application_revision": "revision-1"},
        "input_data": {"files": ["one.mp4"]},
    }
    values.update(overrides)
    return create_run(**values)


@pytest.mark.django_db
def test_create_run_persists_initial_event(organization, actor):
    run = _create_run(organization, actor)

    run.refresh_from_db()
    event = run.events.get()
    assert run.status == Run.Status.QUEUED
    assert run.version == 1
    assert run.next_event_sequence == 1
    assert event.sequence == 1
    assert event.type == "run.queued"
    assert event.organization_id == organization.id


@pytest.mark.django_db(transaction=True)
def test_database_claim_creates_attempt_lease_and_ordered_event(organization, actor):
    run = _create_run(organization, actor)

    claimed = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
        lease_seconds=30,
    )

    assert claimed is not None
    assert claimed.run.id == run.id
    assert claimed.attempt.attempt_no == 1
    assert claimed.lease.epoch == 1
    assert claimed.lease.worker_id == "local-coordinator"
    run.refresh_from_db()
    assert run.status == Run.Status.RUNNING
    assert run.current_attempt_id == claimed.attempt.id
    assert list(run.events.values_list("sequence", flat=True)) == [1, 2]
    assert claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    ) is None


@pytest.mark.django_db(transaction=True)
def test_worker_event_requires_current_lease_fence(organization, actor):
    run = _create_run(organization, actor)
    claimed = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    fence = LeaseFence(token=claimed.lease.token, epoch=claimed.lease.epoch)

    event = append_event_and_transition(
        run_id=run.id,
        organization_id=organization.id,
        event_type="progress.updated",
        payload={"current": 1, "total": 2},
        attempt_id=claimed.attempt.id,
        lease_fence=fence,
    )
    assert event.sequence == 3

    RunLease.objects.filter(pk=claimed.lease.pk).update(released_at=timezone.now())
    with pytest.raises(LeaseLost):
        append_event_and_transition(
            run_id=run.id,
            organization_id=organization.id,
            event_type="output.delta",
            payload={"text": "stale"},
            attempt_id=claimed.attempt.id,
            lease_fence=fence,
        )
    assert list(RunEvent.objects.filter(run=run).values_list("sequence", flat=True)) == [1, 2, 3]


@pytest.mark.django_db(transaction=True)
def test_renew_lease_rejects_released_lease(organization, actor):
    run = _create_run(organization, actor)
    claimed = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    assert renew_lease(
        lease_token=claimed.lease.token,
        lease_epoch=claimed.lease.epoch,
    )

    RunLease.objects.filter(pk=claimed.lease.pk).update(released_at=timezone.now())
    assert not renew_lease(
        lease_token=claimed.lease.token,
        lease_epoch=claimed.lease.epoch,
    )


@pytest.mark.django_db(transaction=True)
def test_finish_attempt_releases_lease_and_closes_run(organization, actor):
    run = _create_run(organization, actor)
    claimed = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    event = finish_attempt(
        run_id=run.id,
        organization_id=organization.id,
        attempt_id=claimed.attempt.id,
        lease_fence=LeaseFence(
            token=claimed.lease.token,
            epoch=claimed.lease.epoch,
        ),
        outcome=Run.Status.SUCCEEDED,
        output_summary={"transcripts": 1},
    )

    run.refresh_from_db()
    claimed.attempt.refresh_from_db()
    claimed.lease.refresh_from_db()
    assert event.sequence == 3
    assert run.status == Run.Status.SUCCEEDED
    assert run.current_attempt_id is None
    assert run.output_summary == {"transcripts": 1}
    assert claimed.attempt.status == claimed.attempt.Status.SUCCEEDED
    assert claimed.lease.released_at is not None


@pytest.mark.django_db(transaction=True)
def test_failed_attempt_is_retried_without_changing_snapshot(organization, actor):
    run = _create_run(organization, actor, max_attempts=2)
    original_snapshot = run.definition_snapshot
    claimed = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )

    event = fail_attempt(
        run_id=run.id,
        organization_id=organization.id,
        attempt_id=claimed.attempt.id,
        lease_fence=LeaseFence(
            token=claimed.lease.token,
            epoch=claimed.lease.epoch,
        ),
        error_code="adapter_failed",
        error_message="transient adapter failure",
    )

    run.refresh_from_db()
    claimed.attempt.refresh_from_db()
    claimed.lease.refresh_from_db()
    assert event.type == "run.retry_scheduled"
    assert run.status == Run.Status.QUEUED
    assert run.current_attempt_id is None
    assert run.definition_snapshot == original_snapshot
    assert claimed.attempt.status == claimed.attempt.Status.FAILED
    assert claimed.lease.released_at is not None


@pytest.mark.django_db(transaction=True)
def test_checkpoint_answer_and_resume_are_durable(organization, actor):
    # A human-input suspension is not a failed attempt and must not consume
    # the retry budget, even when the failure budget is one.
    run = _create_run(organization, actor, max_attempts=1)
    first = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    fence = LeaseFence(token=first.lease.token, epoch=first.lease.epoch)
    checkpoint, artifact_event, created = record_artifact(
        run_id=run.id,
        organization_id=organization.id,
        attempt_id=first.attempt.id,
        lease_fence=fence,
        kind="checkpoint",
        object_key=f"v2/{organization.id}/runs/{run.id}/checkpoint.json",
        content_hash="a" * 64,
        mime_type="application/json",
        size=42,
    )
    input_request_id = uuid.uuid4()
    required_event = suspend_attempt_for_input(
        run_id=run.id,
        organization_id=organization.id,
        attempt_id=first.attempt.id,
        lease_fence=fence,
        checkpoint_artifact_id=checkpoint.id,
        input_request_id=input_request_id,
        input_kind=Run.InputKind.ANSWER,
        expires_at=timezone.now() + timedelta(minutes=10),
        request_payload={"prompt": "Continue?"},
    )

    run.refresh_from_db()
    first.attempt.refresh_from_db()
    first.lease.refresh_from_db()
    assert created is True
    assert artifact_event.type == "artifact.created"
    assert required_event.type == "input.required"
    assert run.status == Run.Status.WAITING_INPUT
    assert run.current_attempt_id is None
    assert run.pending_input_request_id == input_request_id
    assert first.attempt.status == first.attempt.Status.SUSPENDED
    assert first.attempt.checkpoint_artifact_id == checkpoint.id
    assert first.lease.released_at is not None

    command, replayed = submit_run_command(
        run_id=run.id,
        organization_id=organization.id,
        actor=actor,
        command_type="answer",
        idempotency_key="answer-input-request",
        input_request_id=input_request_id,
        payload={"answer": "yes"},
    )
    run.refresh_from_db()
    assert replayed is False
    assert command.result["run_status"] == Run.Status.QUEUED
    assert run.status == Run.Status.QUEUED
    assert run.pending_input_request_id is None

    second = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    command.refresh_from_db()
    assert second.attempt.attempt_no == 2
    assert second.attempt.checkpoint_artifact_id == checkpoint.id
    assert second.resume_command.id == command.id
    assert command.consumed_at is not None
    assert list(run.events.values_list("sequence", "type")) == [
        (1, "run.queued"),
        (2, "run.started"),
        (3, "artifact.created"),
        (4, "input.required"),
        (5, "input.accepted"),
        (6, "run.started"),
    ]


@pytest.mark.django_db(transaction=True)
def test_expired_input_request_is_cancelled(organization, actor):
    run = _create_run(organization, actor)
    claimed = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    fence = LeaseFence(token=claimed.lease.token, epoch=claimed.lease.epoch)
    checkpoint, _event, _created = record_artifact(
        run_id=run.id,
        organization_id=organization.id,
        attempt_id=claimed.attempt.id,
        lease_fence=fence,
        kind="checkpoint",
        object_key="checkpoint.json",
        content_hash="b" * 64,
        mime_type="application/json",
        size=1,
    )
    request_id = uuid.uuid4()
    suspend_attempt_for_input(
        run_id=run.id,
        organization_id=organization.id,
        attempt_id=claimed.attempt.id,
        lease_fence=fence,
        checkpoint_artifact_id=checkpoint.id,
        input_request_id=request_id,
        input_kind=Run.InputKind.PERMISSION,
        expires_at=timezone.now() + timedelta(minutes=1),
        request_payload={"permission": "filesystem.read"},
    )
    Run.objects.filter(pk=run.id).update(
        pending_input_expires_at=timezone.now() - timedelta(seconds=1)
    )

    events = expire_waiting_inputs()

    run.refresh_from_db()
    assert [event.type for event in events] == ["input.expired"]
    assert run.status == Run.Status.CANCELLED
    assert run.pending_input_request_id is None
    assert run.finished_at is not None


@pytest.mark.django_db(transaction=True)
def test_reaper_fences_old_attempt_and_schedules_retry(organization, actor):
    run = _create_run(organization, actor, max_attempts=2)
    first = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    old_fence = LeaseFence(token=first.lease.token, epoch=first.lease.epoch)
    RunLease.objects.filter(pk=first.lease.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    events = reap_expired_leases()
    assert [event.type for event in events] == ["run.retry_scheduled"]
    run.refresh_from_db()
    assert run.status == Run.Status.QUEUED
    assert run.current_attempt_id is None

    second = claim_next_run(
        worker_id="local-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    assert second.attempt.attempt_no == 2
    assert second.lease.epoch == 2
    with pytest.raises(LeaseLost):
        append_event_and_transition(
            run_id=run.id,
            organization_id=organization.id,
            event_type="output.delta",
            payload={"text": "zombie"},
            attempt_id=first.attempt.id,
            lease_fence=old_fence,
        )


@pytest.mark.django_db
def test_event_append_rejects_cross_tenant_access(organization, actor):
    run = _create_run(organization, actor)
    with pytest.raises(OrganizationMismatch):
        append_event_and_transition(
            run_id=run.id,
            organization_id="00000000-0000-0000-0000-000000000001",
            event_type="progress.updated",
            payload={},
        )


@pytest.mark.django_db
def test_organization_visibility_is_membership_scoped(organization, actor):
    outsider = get_user_model().objects.create_user(username="v2-outsider")
    assert list(Organization.objects.visible_to(actor)) == [organization]
    assert not Organization.objects.visible_to(outsider).exists()


@pytest.mark.django_db
def test_database_rejects_waiting_input_without_request_projection(organization, actor):
    run = _create_run(organization, actor)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Run.objects.filter(pk=run.id).update(status=Run.Status.WAITING_INPUT)

    with pytest.raises(InvalidRunTransition, match="suspend_attempt_for_input"):
        append_event_and_transition(
            run_id=run.id,
            organization_id=organization.id,
            event_type="input.required",
            payload={},
            new_status=Run.Status.WAITING_INPUT,
        )


@pytest.mark.django_db
def test_database_allows_only_one_unfinished_attempt(organization, actor):
    run = _create_run(organization, actor)
    RunAttempt.objects.create(
        run=run,
        attempt_no=1,
        worker_pool=Run.ExecutorKind.MEDIA,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RunAttempt.objects.create(
                run=run,
                attempt_no=2,
                worker_pool=Run.ExecutorKind.MEDIA,
            )


def test_coordinator_file_lock_is_exclusive(tmp_path):
    database_path = Path(tmp_path) / "local.sqlite3"
    first = CoordinatorFileLock(database_path).acquire()
    try:
        with pytest.raises(CoordinatorAlreadyRunning):
            CoordinatorFileLock(database_path).acquire()
    finally:
        first.release()

    second = CoordinatorFileLock(database_path).acquire()
    second.release()

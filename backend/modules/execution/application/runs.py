import logging
import time
from dataclasses import dataclass
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import OperationalError, transaction
from django.utils import timezone

from modules.execution.models import (
    Run,
    RunArtifact,
    RunAttempt,
    RunEvent,
    RunLease,
    RunQueueEntry,
)
from modules.execution.telemetry import finish_execution_span, start_execution_span

from .errors import (
    ConcurrentRunUpdate,
    InvalidRunTransition,
    LeaseLost,
    OrganizationMismatch,
)
from .ports import execution_domain_port


logger = logging.getLogger(__name__)


TERMINAL_STATUSES = {
    Run.Status.SUCCEEDED,
    Run.Status.FAILED,
    Run.Status.CANCELLED,
}

ALLOWED_TRANSITIONS = {
    Run.Status.QUEUED: {Run.Status.RUNNING, Run.Status.CANCELLED},
    Run.Status.RUNNING: {
        Run.Status.WAITING_INPUT,
        Run.Status.WAITING_CHILDREN,
        Run.Status.CANCELLING,
        Run.Status.QUEUED,
        Run.Status.SUCCEEDED,
        Run.Status.FAILED,
    },
    Run.Status.WAITING_INPUT: {Run.Status.QUEUED, Run.Status.CANCELLED},
    Run.Status.WAITING_CHILDREN: {Run.Status.QUEUED, Run.Status.CANCELLED},
    Run.Status.CANCELLING: {Run.Status.CANCELLED},
    Run.Status.SUCCEEDED: set(),
    Run.Status.FAILED: set(),
    Run.Status.CANCELLED: set(),
}


@dataclass(frozen=True)
class LeaseFence:
    token: UUID
    epoch: int


def _publish_event_notification(run_id, sequence):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            f"run-{run_id}",
            {
                "type": "run.event.available",
                "run_id": str(run_id),
                "sequence": sequence,
            },
        )
    except Exception:
        logger.warning(
            "Failed to publish run event notification",
            exc_info=True,
            extra={"run_id": str(run_id), "sequence": sequence},
        )


def _validate_transition(current_status, new_status):
    if new_status is None or new_status == current_status:
        return
    if new_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidRunTransition(f"Cannot transition {current_status} -> {new_status}")


def _validate_lease(run, fence, now):
    if fence is None:
        return None
    if run.current_attempt_id is None:
        raise LeaseLost("Run has no current attempt")
    try:
        lease = RunLease.objects.select_related("attempt").get(
            attempt_id=run.current_attempt_id,
            token=fence.token,
            epoch=fence.epoch,
            released_at__isnull=True,
        )
    except RunLease.DoesNotExist as exc:
        raise LeaseLost("Lease token or epoch is no longer current") from exc
    if lease.expires_at <= now:
        raise LeaseLost("Lease has expired")
    return lease


def sync_run_queue_entry(run):
    """Keep the global claim index consistent with the locked Run projection."""

    if run.status == Run.Status.QUEUED and run.current_attempt_id is None:
        RunQueueEntry.objects.update_or_create(
            run=run,
            defaults={
                "organization_id": run.organization_id,
                "worker_pool": run.executor_kind,
                "executor_key": run.executor_key,
                "priority": run.priority,
            },
        )
    else:
        RunQueueEntry.objects.filter(run=run).delete()


def create_run(
    *,
    organization,
    owner,
    executor_kind,
    executor_key="",
    source_type,
    source_id="",
    definition_snapshot,
    input_data,
    priority=0,
    max_attempts=3,
    retry_safe=True,
    parent=None,
    node_key="",
):
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    if parent is not None and parent.organization_id != organization.id:
        raise OrganizationMismatch("Parent Run belongs to another organization")
    if parent is not None and not node_key:
        raise ValueError("Child Runs require a node_key")
    execution_domain_port().enforce_member_token_quota(organization, owner)
    now = timezone.now()
    with transaction.atomic():
        run = Run.objects.create(
            organization=organization,
            owner=owner,
            parent=parent,
            node_key=node_key,
            executor_kind=executor_kind,
            executor_key=executor_key,
            source_type=source_type,
            source_id=str(source_id or ""),
            status=Run.Status.QUEUED,
            priority=priority,
            max_attempts=max_attempts,
            retry_safe=retry_safe,
            definition_snapshot=definition_snapshot,
            input=input_data,
            version=1,
            next_event_sequence=1,
        )
        event = RunEvent.objects.create(
            organization=organization,
            run=run,
            sequence=1,
            type="run.queued",
            payload={"queued_at": now.isoformat()},
        )
        sync_run_queue_entry(run)
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
    span = start_execution_span("execution.run.create", run=run)
    finish_execution_span(span, outcome=Run.Status.QUEUED)
    return run


def mirror_child_output_event(*, child_run_id, organization_id, event_type, payload):
    """Append a child output event to its parent workflow's ordered stream."""
    if event_type not in {"output.delta", "output.snapshot"}:
        return None
    with transaction.atomic():
        child = Run.objects.select_related("parent").get(pk=child_run_id)
        if str(child.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")
        if child.parent_id is None or child.source_type not in {
            "workflow_step", "supervisor_task"
        }:
            return None
        parent = Run.objects.select_for_update().get(pk=child.parent_id)
        snapshot = child.definition_snapshot or {}
        parent.version += 1
        parent.next_event_sequence += 1
        parent.save(update_fields=("version", "next_event_sequence"))
        is_supervisor = child.source_type == "supervisor_task"
        event = RunEvent.objects.create(
            organization_id=parent.organization_id,
            run=parent,
            sequence=parent.next_event_sequence,
            type=(
                f"supervisor.task.{event_type}"
                if is_supervisor else f"workflow.step.{event_type}"
            ),
            payload=({
                "task_key": snapshot.get("supervisor_task_key") or child.node_key,
                "task_title": snapshot.get("supervisor_task_title") or child.node_key,
                "plan_version": snapshot.get("supervisor_plan_version"),
                "target_type": snapshot.get("supervisor_target_type"),
                "target_id": snapshot.get("supervisor_target_id"),
                "child_run_id": str(child.id),
                **dict(payload or {}),
            } if is_supervisor else {
                "workflow_step_id": snapshot.get("workflow_step_id") or child.source_id,
                "workflow_step_key": snapshot.get("workflow_step_key") or child.node_key,
                "workflow_step_name": snapshot.get("workflow_step_name") or child.node_key,
                "child_run_id": str(child.id),
                **dict(payload or {}),
            }),
        )
        transaction.on_commit(
            lambda: _publish_event_notification(parent.id, event.sequence)
        )
    return event


def record_artifact(
    *,
    run_id,
    organization_id,
    attempt_id,
    lease_fence,
    kind,
    object_key,
    content_hash,
    mime_type,
    size,
    metadata=None,
):
    """Fence and persist artifact metadata with its ordered Run event."""

    if not kind or not object_key or not mime_type:
        raise ValueError("kind, object_key and mime_type are required")
    if len(content_hash) != 64:
        raise ValueError("content_hash must be a SHA-256 hex digest")
    if size < 0:
        raise ValueError("size must not be negative")
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if str(run.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")
        now = timezone.now()
        _validate_lease(run, lease_fence, now)
        if run.current_attempt_id != attempt_id:
            raise LeaseLost("Attempt is no longer current")

        existing = RunArtifact.objects.filter(
            run=run,
            object_key=object_key,
            content_hash=content_hash,
        ).first()
        if existing is not None:
            return existing, None, False

        artifact = RunArtifact.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt_id=attempt_id,
            kind=kind,
            object_key=object_key,
            content_hash=content_hash,
            mime_type=mime_type,
            size=size,
            metadata=metadata or {},
        )
        run.version += 1
        run.next_event_sequence += 1
        run.save(update_fields=("version", "next_event_sequence"))
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt_id=attempt_id,
            sequence=run.next_event_sequence,
            type="artifact.created",
            payload={
                "artifact_id": str(artifact.id),
                "kind": artifact.kind,
                "content_hash": artifact.content_hash,
                "mime_type": artifact.mime_type,
                "size": artifact.size,
            },
        )
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
    return artifact, event, True


def suspend_attempt_for_input(
    *,
    run_id,
    organization_id,
    attempt_id,
    lease_fence,
    checkpoint_artifact_id,
    input_request_id,
    input_kind,
    expires_at,
    request_payload,
):
    """Release a Worker only after a durable checkpoint can resume the Run."""

    if input_kind not in Run.InputKind.values:
        raise ValueError(f"Unsupported input kind: {input_kind}")
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if str(run.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")
        now = timezone.now()
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
        lease = _validate_lease(run, lease_fence, now)
        if run.current_attempt_id != attempt_id:
            raise LeaseLost("Attempt is no longer current")
        _validate_transition(run.status, Run.Status.WAITING_INPUT)
        checkpoint = RunArtifact.objects.select_for_update().get(
            pk=checkpoint_artifact_id,
            organization_id=run.organization_id,
            run=run,
            attempt_id=attempt_id,
            kind="checkpoint",
        )
        attempt = RunAttempt.objects.select_for_update().get(pk=attempt_id, run=run)

        attempt.status = RunAttempt.Status.SUSPENDED
        attempt.checkpoint_artifact = checkpoint
        attempt.finished_at = now
        attempt.save(
            update_fields=("status", "checkpoint_artifact", "finished_at")
        )
        lease.released_at = now
        lease.save(update_fields=("released_at",))

        run.status = Run.Status.WAITING_INPUT
        run.current_attempt = None
        run.pending_input_request_id = input_request_id
        run.pending_input_kind = input_kind
        run.pending_input_expires_at = expires_at
        run.version += 1
        run.next_event_sequence += 1
        run.save(
            update_fields=(
                "status",
                "current_attempt",
                "pending_input_request_id",
                "pending_input_kind",
                "pending_input_expires_at",
                "version",
                "next_event_sequence",
            )
        )
        sync_run_queue_entry(run)
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt=attempt,
            sequence=run.next_event_sequence,
            type="input.required",
            payload={
                **(request_payload or {}),
                "input_request_id": str(input_request_id),
                "input_kind": input_kind,
                "expires_at": expires_at.isoformat(),
                "checkpoint_artifact_id": str(checkpoint.id),
            },
        )
        parent_id = run.parent_id
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
        if parent_id:
            transaction.on_commit(
                lambda: wake_waiting_parent(
                    parent_id=parent_id,
                    organization_id=organization_id,
                    child_run_id=run.id,
                )
            )
    return event


def suspend_attempt_for_children(
    *,
    run_id,
    organization_id,
    attempt_id,
    lease_fence,
    checkpoint_artifact_id,
    child_run_ids,
):
    """Release a workflow Worker until one of its durable children changes state."""

    child_run_ids = tuple(dict.fromkeys(child_run_ids))
    if not child_run_ids:
        raise ValueError("At least one child Run is required")
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if str(run.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")
        now = timezone.now()
        lease = _validate_lease(run, lease_fence, now)
        if run.current_attempt_id != attempt_id:
            raise LeaseLost("Attempt is no longer current")
        _validate_transition(run.status, Run.Status.WAITING_CHILDREN)
        checkpoint = RunArtifact.objects.select_for_update().get(
            pk=checkpoint_artifact_id,
            organization_id=run.organization_id,
            run=run,
            attempt_id=attempt_id,
            kind="checkpoint",
        )
        children = Run.objects.filter(
            parent=run,
            id__in=child_run_ids,
        )
        if children.count() != len(child_run_ids):
            raise OrganizationMismatch("A dependency Run is not a child of this workflow")
        has_active_children = children.exclude(status__in=TERMINAL_STATUSES).exists()
        next_status = (
            Run.Status.WAITING_CHILDREN
            if has_active_children
            else Run.Status.QUEUED
        )
        attempt = RunAttempt.objects.select_for_update().get(pk=attempt_id, run=run)
        attempt.status = RunAttempt.Status.SUSPENDED
        attempt.checkpoint_artifact = checkpoint
        attempt.finished_at = now
        attempt.save(update_fields=("status", "checkpoint_artifact", "finished_at"))
        lease.released_at = now
        lease.save(update_fields=("released_at",))

        run.status = next_status
        run.current_attempt = None
        run.version += 1
        run.next_event_sequence += 1
        run.save(update_fields=(
            "status", "current_attempt", "version", "next_event_sequence",
        ))
        sync_run_queue_entry(run)
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt=attempt,
            sequence=run.next_event_sequence,
            type=(
                "run.waiting_children"
                if has_active_children
                else "run.dependencies_ready"
            ),
            payload={
                "child_run_ids": [str(value) for value in child_run_ids],
                "checkpoint_artifact_id": str(checkpoint.id),
            },
        )
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
    return event


def wake_waiting_parent(*, parent_id, organization_id, child_run_id):
    """Requeue a suspended workflow after a child terminal/input transition."""

    from modules.tenancy.database import tenant_database_context

    with tenant_database_context(organization_id):
        with transaction.atomic():
            parent = Run.objects.select_for_update().filter(
                pk=parent_id,
                organization_id=organization_id,
                status=Run.Status.WAITING_CHILDREN,
                current_attempt__isnull=True,
            ).first()
            if parent is None:
                return None
            parent.status = Run.Status.QUEUED
            parent.version += 1
            parent.next_event_sequence += 1
            parent.save(update_fields=("status", "version", "next_event_sequence"))
            sync_run_queue_entry(parent)
            event = RunEvent.objects.create(
                organization_id=parent.organization_id,
                run=parent,
                sequence=parent.next_event_sequence,
                type="run.dependencies_ready",
                payload={"child_run_id": str(child_run_id)},
            )
            transaction.on_commit(
                lambda: _publish_event_notification(parent.id, event.sequence)
            )
    return event


def append_event_and_transition(
    *,
    run_id,
    organization_id,
    event_type,
    payload,
    new_status=None,
    attempt_id=None,
    lease_fence=None,
    expected_version=None,
    max_retries=4,
):
    """Append one ordered event and update the Run projection atomically.

    PostgreSQL row locks serialize writers. The version compare-and-swap is
    also required so SQLite cannot silently allocate duplicate sequences.
    """

    for retry_no in range(max_retries):
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                if str(run.organization_id) != str(organization_id):
                    raise OrganizationMismatch("Run belongs to another organization")
                if expected_version is not None and run.version != expected_version:
                    raise ConcurrentRunUpdate(
                        f"Expected run version {expected_version}, found {run.version}"
                    )
                now = timezone.now()
                _validate_lease(run, lease_fence, now)
                if new_status == Run.Status.WAITING_INPUT:
                    raise InvalidRunTransition(
                        "Use suspend_attempt_for_input() to enter waiting_input"
                    )
                if new_status == Run.Status.WAITING_CHILDREN:
                    raise InvalidRunTransition(
                        "Use suspend_attempt_for_children() to enter waiting_children"
                    )
                if (
                    run.status == Run.Status.WAITING_INPUT
                    and new_status == Run.Status.QUEUED
                ):
                    raise InvalidRunTransition(
                        "Use an input command to resume a waiting_input Run"
                    )
                _validate_transition(run.status, new_status)

                next_sequence = run.next_event_sequence + 1
                updates = {
                    "next_event_sequence": next_sequence,
                    "version": run.version + 1,
                }
                if new_status is not None:
                    updates["status"] = new_status
                    if new_status == Run.Status.RUNNING and run.started_at is None:
                        updates["started_at"] = now
                    if new_status in TERMINAL_STATUSES:
                        updates["finished_at"] = now

                updated = Run.objects.filter(pk=run.pk, version=run.version).update(
                    **updates
                )
                if updated != 1:
                    raise ConcurrentRunUpdate("Run projection changed concurrently")

                if new_status is not None:
                    run.status = new_status
                run.version = updates["version"]
                run.next_event_sequence = next_sequence
                sync_run_queue_entry(run)

                event = RunEvent.objects.create(
                    organization_id=run.organization_id,
                    run_id=run.id,
                    attempt_id=attempt_id,
                    sequence=next_sequence,
                    type=event_type,
                    payload=payload,
                )
                transaction.on_commit(
                    lambda: _publish_event_notification(run.id, event.sequence)
                )
            return event
        except OperationalError as exc:
            is_busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not is_busy or retry_no + 1 >= max_retries:
                raise
            time.sleep(0.01 * (2**retry_no))

    raise ConcurrentRunUpdate("Unable to append event after retries")


def finish_attempt(
    *,
    run_id,
    organization_id,
    attempt_id,
    lease_fence,
    outcome,
    output_summary=None,
    error_code="",
    error_message="",
):
    outcome_map = {
        Run.Status.SUCCEEDED: (RunAttempt.Status.SUCCEEDED, "run.succeeded"),
        Run.Status.FAILED: (RunAttempt.Status.FAILED, "run.failed"),
        Run.Status.CANCELLED: (RunAttempt.Status.CANCELLED, "run.cancelled"),
    }
    if outcome not in outcome_map:
        raise ValueError(f"Unsupported terminal outcome: {outcome}")

    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if str(run.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")
        now = timezone.now()
        lease = _validate_lease(run, lease_fence, now)
        if run.current_attempt_id != attempt_id:
            raise LeaseLost("Attempt is no longer current")
        _validate_transition(run.status, outcome)

        attempt_status, event_type = outcome_map[outcome]
        attempt = RunAttempt.objects.select_for_update().get(pk=attempt_id, run=run)
        attempt.status = attempt_status
        attempt.finished_at = now
        attempt.error_code = error_code
        attempt.save(update_fields=("status", "finished_at", "error_code"))

        lease.released_at = now
        lease.save(update_fields=("released_at",))

        run.status = outcome
        run.current_attempt = None
        run.finished_at = now
        run.output_summary = output_summary or {}
        run.error_code = error_code
        run.error_message = error_message
        run.version += 1
        run.next_event_sequence += 1
        run.save(
            update_fields=(
                "status",
                "current_attempt",
                "finished_at",
                "output_summary",
                "error_code",
                "error_message",
                "version",
                "next_event_sequence",
            )
        )
        sync_run_queue_entry(run)
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt=attempt,
            sequence=run.next_event_sequence,
            type=event_type,
            payload={
                "attempt_no": attempt.attempt_no,
                "error_code": error_code,
            },
        )
        parent_id = run.parent_id
        if outcome == Run.Status.CANCELLED:
            from modules.execution.application.projections import project_terminal_run
            project_terminal_run(run.id, run.output_summary)
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
        if parent_id:
            transaction.on_commit(
                lambda: wake_waiting_parent(
                    parent_id=parent_id,
                    organization_id=organization_id,
                    child_run_id=run.id,
                )
            )
    return event


def fail_attempt(
    *,
    run_id,
    organization_id,
    attempt_id,
    lease_fence,
    error_code,
    error_message,
):
    """Fail one attempt and either retry its immutable Run or close it."""

    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if str(run.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")
        now = timezone.now()
        lease = _validate_lease(run, lease_fence, now)
        if run.current_attempt_id != attempt_id:
            raise LeaseLost("Attempt is no longer current")
        if run.status not in {Run.Status.RUNNING, Run.Status.CANCELLING}:
            raise InvalidRunTransition(f"Cannot fail attempt while Run is {run.status}")

        attempt = RunAttempt.objects.select_for_update().get(pk=attempt_id, run=run)
        attempt.status = RunAttempt.Status.FAILED
        attempt.finished_at = now
        attempt.error_code = error_code
        attempt.save(update_fields=("status", "finished_at", "error_code"))
        lease.released_at = now
        lease.save(update_fields=("released_at",))

        failed_attempts = run.attempts.filter(
            status__in=(RunAttempt.Status.FAILED, RunAttempt.Status.INTERRUPTED)
        ).count()
        if run.status == Run.Status.CANCELLING:
            next_status = Run.Status.CANCELLED
            event_type = "run.cancelled"
            payload = {"reason": "cancelled_during_attempt_failure"}
        elif run.retry_safe and failed_attempts < run.max_attempts:
            next_status = Run.Status.QUEUED
            event_type = "run.retry_scheduled"
            payload = {
                "error_code": error_code,
                "error_message": error_message,
                "previous_attempt_no": attempt.attempt_no,
                "next_attempt_no": attempt.attempt_no + 1,
            }
        else:
            next_status = Run.Status.FAILED
            event_type = "run.failed"
            payload = {
                "error_code": error_code,
                "error_message": error_message,
            }

        run.status = next_status
        run.current_attempt = None
        run.error_code = error_code if next_status == Run.Status.FAILED else ""
        run.error_message = error_message if next_status == Run.Status.FAILED else ""
        run.finished_at = now if next_status in TERMINAL_STATUSES else None
        run.version += 1
        run.next_event_sequence += 1
        run.save(
            update_fields=(
                "status",
                "current_attempt",
                "error_code",
                "error_message",
                "finished_at",
                "version",
                "next_event_sequence",
            )
        )
        sync_run_queue_entry(run)
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt=attempt,
            sequence=run.next_event_sequence,
            type=event_type,
            payload=payload,
        )
        parent_id = run.parent_id if next_status in TERMINAL_STATUSES else None
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
        if parent_id:
            transaction.on_commit(
                lambda: wake_waiting_parent(
                    parent_id=parent_id,
                    organization_id=organization_id,
                    child_run_id=run.id,
                )
            )
    return event

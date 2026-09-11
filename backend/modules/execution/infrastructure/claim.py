from dataclasses import dataclass
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from modules.execution.models import Run, RunAttempt, RunCommand, RunEvent, RunLease
from modules.execution.application.runs import _publish_event_notification


@dataclass(frozen=True)
class ClaimedRun:
    run: Run
    attempt: RunAttempt
    lease: RunLease
    resume_command: RunCommand | None = None


def _claim_locked_run(run, *, worker_id, worker_pool, lease_seconds):
    if run.current_attempt_id is not None or run.status != Run.Status.QUEUED:
        return None
    now = timezone.now()
    attempt_no = run.attempt_count + 1
    lease_epoch = run.next_lease_epoch + 1
    checkpoint_artifact_id = (
        RunAttempt.objects.filter(
            run=run,
            status=RunAttempt.Status.SUSPENDED,
            checkpoint_artifact__isnull=False,
        )
        .order_by("-attempt_no")
        .values_list("checkpoint_artifact_id", flat=True)
        .first()
    )
    resume_command = (
        RunCommand.objects.filter(
            run=run,
            consumed_at__isnull=True,
            type__in=(
                RunCommand.Type.ANSWER,
                RunCommand.Type.GRANT_PERMISSION,
                RunCommand.Type.DENY_PERMISSION,
            ),
        )
        .order_by("-created_at", "-id")
        .first()
    )
    attempt = RunAttempt.objects.create(
        run=run,
        attempt_no=attempt_no,
        status=RunAttempt.Status.RUNNING,
        worker_pool=worker_pool,
        checkpoint_artifact_id=checkpoint_artifact_id,
    )
    lease = RunLease.objects.create(
        attempt=attempt,
        worker_id=worker_id,
        epoch=lease_epoch,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=lease_seconds),
    )

    run.current_attempt = attempt
    run.attempt_count = attempt_no
    run.next_lease_epoch = lease_epoch
    run.status = Run.Status.RUNNING
    run.started_at = run.started_at or now
    run.version += 1
    run.next_event_sequence += 1
    run.save(
        update_fields=(
            "current_attempt",
            "attempt_count",
            "next_lease_epoch",
            "status",
            "started_at",
            "version",
            "next_event_sequence",
        )
    )
    RunEvent.objects.create(
        organization_id=run.organization_id,
        run=run,
        attempt=attempt,
        sequence=run.next_event_sequence,
        type="run.started",
        payload={
            "attempt_no": attempt_no,
            "worker_pool": worker_pool,
            "resumed": checkpoint_artifact_id is not None,
            "checkpoint_artifact_id": (
                str(checkpoint_artifact_id) if checkpoint_artifact_id else None
            ),
        },
    )
    if resume_command is not None:
        resume_command.consumed_at = now
        resume_command.save(update_fields=("consumed_at",))
    return ClaimedRun(
        run=run,
        attempt=attempt,
        lease=lease,
        resume_command=resume_command,
    )


def _claim_postgresql(*, worker_id, worker_pool, lease_seconds, executor_keys):
    with transaction.atomic():
        run = (
            Run.objects.select_for_update(skip_locked=True)
            .queued_for_pool(worker_pool, executor_keys)
            .first()
        )
        if run is None:
            claimed = None
        else:
            claimed = _claim_locked_run(
                run,
                worker_id=worker_id,
                worker_pool=worker_pool,
                lease_seconds=lease_seconds,
            )
    if claimed is not None:
        _publish_event_notification(claimed.run.id, claimed.run.next_event_sequence)
    return claimed


def _claim_sqlite(*, worker_id, worker_pool, lease_seconds, executor_keys):
    if connection.in_atomic_block:
        raise RuntimeError("SQLite claim must run outside transaction.atomic()")

    with connection.cursor() as cursor:
        cursor.execute("BEGIN IMMEDIATE")
    try:
        run = Run.objects.queued_for_pool(worker_pool, executor_keys).first()
        claimed = None
        if run is not None:
            claimed = _claim_locked_run(
                run,
                worker_id=worker_id,
                worker_pool=worker_pool,
                lease_seconds=lease_seconds,
            )
        connection.commit()
        if claimed is not None:
            _publish_event_notification(claimed.run.id, claimed.run.next_event_sequence)
        return claimed
    except Exception:
        connection.rollback()
        raise


def claim_next_run(*, worker_id, worker_pool, lease_seconds=30, executor_keys=None):
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be at least one")
    if connection.vendor == "postgresql":
        return _claim_postgresql(
            worker_id=worker_id,
            worker_pool=worker_pool,
            lease_seconds=lease_seconds,
            executor_keys=executor_keys,
        )
    if connection.vendor == "sqlite":
        return _claim_sqlite(
            worker_id=worker_id,
            worker_pool=worker_pool,
            lease_seconds=lease_seconds,
            executor_keys=executor_keys,
        )
    raise RuntimeError(f"Unsupported execution database vendor: {connection.vendor}")


def renew_lease(*, lease_token, lease_epoch, lease_seconds=30):
    now = timezone.now()
    with transaction.atomic():
        lease = (
            RunLease.objects.select_for_update()
            .select_related("attempt__run")
            .get(token=lease_token, epoch=lease_epoch)
        )
        run = lease.attempt.run
        if (
            lease.released_at is not None
            or lease.expires_at <= now
            or run.current_attempt_id != lease.attempt_id
            or run.status not in {Run.Status.RUNNING, Run.Status.CANCELLING}
        ):
            return False
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=lease_seconds)
        lease.save(update_fields=("heartbeat_at", "expires_at"))
        return True

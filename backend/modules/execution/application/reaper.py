from django.db import transaction
from django.utils import timezone

from modules.execution.models import Run, RunAttempt, RunEvent, RunLease

from .runs import _publish_event_notification


def _reap_one(lease_id, now):
    with transaction.atomic():
        try:
            lease = (
                RunLease.objects.select_for_update()
                .select_related("attempt")
                .get(pk=lease_id)
            )
        except RunLease.DoesNotExist:
            return None
        if lease.released_at is not None or lease.expires_at > now:
            return None

        attempt = lease.attempt
        run = Run.objects.select_for_update().get(pk=attempt.run_id)
        lease.released_at = now
        lease.save(update_fields=("released_at",))

        if run.current_attempt_id != attempt.id:
            return None

        previous_failures = run.attempts.filter(
            status__in=(RunAttempt.Status.FAILED, RunAttempt.Status.INTERRUPTED)
        ).count()
        if run.status == Run.Status.CANCELLING:
            next_status = Run.Status.CANCELLED
            attempt_status = RunAttempt.Status.CANCELLED
            event_type = "run.cancelled"
            payload = {"reason": "lease_expired_while_cancelling"}
        elif run.retry_safe and previous_failures + 1 < run.max_attempts:
            next_status = Run.Status.QUEUED
            attempt_status = RunAttempt.Status.INTERRUPTED
            event_type = "run.retry_scheduled"
            payload = {
                "reason": "lease_expired",
                "previous_attempt_no": attempt.attempt_no,
                "next_attempt_no": attempt.attempt_no + 1,
            }
        else:
            next_status = Run.Status.FAILED
            attempt_status = RunAttempt.Status.INTERRUPTED
            event_type = "run.failed"
            payload = {"reason": "lease_expired", "error_code": "worker_lost"}

        attempt.status = attempt_status
        attempt.finished_at = now
        attempt.error_code = "worker_lost"
        attempt.save(update_fields=("status", "finished_at", "error_code"))

        run.status = next_status
        run.current_attempt = None
        run.error_code = "worker_lost" if next_status == Run.Status.FAILED else ""
        run.error_message = "Worker lease expired" if next_status == Run.Status.FAILED else ""
        run.finished_at = now if next_status in {
            Run.Status.FAILED,
            Run.Status.CANCELLED,
        } else None
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
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            attempt=attempt,
            sequence=run.next_event_sequence,
            type=event_type,
            payload=payload,
        )
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
        return event


def reap_expired_leases(*, now=None, limit=100):
    now = now or timezone.now()
    lease_ids = list(
        RunLease.objects.filter(
            released_at__isnull=True,
            expires_at__lte=now,
        )
        .order_by("expires_at")
        .values_list("id", flat=True)[:limit]
    )
    return [event for lease_id in lease_ids if (event := _reap_one(lease_id, now))]


def _expire_input_request(run_id, now):
    with transaction.atomic():
        try:
            run = Run.objects.select_for_update().get(pk=run_id)
        except Run.DoesNotExist:
            return None
        if (
            run.status != Run.Status.WAITING_INPUT
            or run.pending_input_expires_at is None
            or run.pending_input_expires_at > now
        ):
            return None

        input_request_id = run.pending_input_request_id
        run.status = Run.Status.CANCELLED
        run.pending_input_request_id = None
        run.pending_input_kind = ""
        run.pending_input_expires_at = None
        run.finished_at = now
        run.version += 1
        run.next_event_sequence += 1
        run.save(
            update_fields=(
                "status",
                "pending_input_request_id",
                "pending_input_kind",
                "pending_input_expires_at",
                "finished_at",
                "version",
                "next_event_sequence",
            )
        )
        event = RunEvent.objects.create(
            organization_id=run.organization_id,
            run=run,
            sequence=run.next_event_sequence,
            type="input.expired",
            payload={
                "input_request_id": (
                    str(input_request_id) if input_request_id else None
                )
            },
        )
        transaction.on_commit(
            lambda: _publish_event_notification(run.id, event.sequence)
        )
        return event


def expire_waiting_inputs(*, now=None, limit=100):
    now = now or timezone.now()
    run_ids = list(
        Run.objects.filter(
            status=Run.Status.WAITING_INPUT,
            pending_input_expires_at__lte=now,
        )
        .order_by("pending_input_expires_at")
        .values_list("id", flat=True)[:limit]
    )
    return [
        event
        for run_id in run_ids
        if (event := _expire_input_request(run_id, now))
    ]

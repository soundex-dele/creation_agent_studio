"""Lease-fenced input for providers that must keep their process alive."""
from django.db import transaction
from django.utils import timezone

from modules.execution.models import Run, RunEvent
from .errors import LeaseLost
from .runs import _validate_lease, _publish_event_notification


def live_input(*, run_id, organization_id, attempt_id, lease_fence,
               input_request_id, request_payload=None, input_kind="answer", expires_at=None):
    """Create or resolve an input without releasing the active worker lease."""
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
        _validate_lease(run, lease_fence, timezone.now())
        if run.current_attempt_id != attempt_id:
            raise LeaseLost("Live input belongs to an expired attempt")
        resolving = request_payload is None
        if resolving:
            if str(run.pending_input_request_id) != str(input_request_id):
                return None
            run.status = Run.Status.RUNNING
            run.pending_input_request_id = None
            run.pending_input_kind = ""
            run.pending_input_expires_at = None
            kind = "input.resolved"
            payload = {"input_request_id": str(input_request_id), "live": True}
        else:
            if run.status != Run.Status.RUNNING or input_kind not in Run.InputKind.values:
                raise LeaseLost("Run cannot accept a live input request")
            run.status = Run.Status.WAITING_INPUT
            run.pending_input_request_id = input_request_id
            run.pending_input_kind = input_kind
            run.pending_input_expires_at = expires_at
            # A lost RPC process must never replay an outstanding authorization.
            run.retry_safe = False
            kind = "input.required"
            payload = {**request_payload, "input_request_id": str(input_request_id),
                       "input_kind": input_kind, "expires_at": expires_at.isoformat(), "live": True}
        run.version += 1
        run.next_event_sequence += 1
        run.save(update_fields=("status", "pending_input_request_id", "pending_input_kind",
                                "pending_input_expires_at", "retry_safe", "version", "next_event_sequence"))
        event = RunEvent.objects.create(organization_id=run.organization_id, run=run,
                                       attempt_id=attempt_id, sequence=run.next_event_sequence,
                                       type=kind, payload=payload)
        if not resolving:
            from .projections import project_input_required
            project_input_required(run.id, event)
        transaction.on_commit(lambda: _publish_event_notification(run.id, event.sequence))
        if run.parent_id and not resolving:
            from .runs import wake_waiting_parent
            transaction.on_commit(lambda: wake_waiting_parent(
                parent_id=run.parent_id, organization_id=run.organization_id, child_run_id=run.id,
            ))
        return event

from copy import deepcopy
import json

from django.db import transaction

from modules.execution.models import Run, RunEvent, RunEventSnapshot


TERMINAL_STATUSES = {Run.Status.SUCCEEDED, Run.Status.FAILED, Run.Status.CANCELLED}

STATUS_BY_EVENT = {
    "run.queued": Run.Status.QUEUED,
    "run.started": Run.Status.RUNNING,
    "run.waiting_input": Run.Status.WAITING_INPUT,
    "run.cancelling": Run.Status.CANCELLING,
    "run.retry_scheduled": Run.Status.QUEUED,
    "run.succeeded": Run.Status.SUCCEEDED,
    "run.failed": Run.Status.FAILED,
    "run.cancelled": Run.Status.CANCELLED,
}


def empty_projection(run_id):
    return {
        "runId": str(run_id),
        "nextSequence": 1,
        "status": None,
        "output": "",
        "progress": None,
        "tools": {},
        "pendingInput": None,
        "artifactIds": [],
    }


def apply_projection_event(projection, event):
    next_projection = deepcopy(projection)
    next_projection["runId"] = str(event.run_id)
    next_projection["nextSequence"] = event.sequence + 1
    if event.type in STATUS_BY_EVENT:
        next_projection["status"] = STATUS_BY_EVENT[event.type]

    payload = event.payload
    if event.type == "output.delta":
        next_projection["output"] = next_projection.get("output", "") + str(
            payload.get("text", "")
        )
    elif event.type == "output.snapshot":
        value = payload.get("text", payload.get("output", payload.get("result", "")))
        if isinstance(value, str):
            next_projection["output"] = value
        elif value == "":
            next_projection["output"] = ""
        else:
            next_projection["output"] = json.dumps(
                value, ensure_ascii=False, indent=2
            )
    elif event.type == "progress.updated":
        next_projection["progress"] = payload
    elif event.type == "input.required":
        next_projection["status"] = Run.Status.WAITING_INPUT
        next_projection["pendingInput"] = payload
    elif event.type == "input.accepted":
        next_projection["status"] = Run.Status.QUEUED
        next_projection["pendingInput"] = None
    elif event.type == "input.expired":
        next_projection["status"] = Run.Status.CANCELLED
        next_projection["pendingInput"] = None
    elif event.type == "artifact.created":
        artifact_id = str(payload.get("artifact_id", ""))
        artifact_ids = next_projection.setdefault("artifactIds", [])
        if artifact_id and artifact_id not in artifact_ids:
            artifact_ids.append(artifact_id)
    elif event.type in {"tool.started", "tool.completed", "tool.failed"}:
        tool_id = str(
            payload.get("tool_call_id")
            or payload.get("call_id")
            or f"sequence-{event.sequence}"
        )
        tools = next_projection.setdefault("tools", {})
        tools[tool_id] = {
            **tools.get(tool_id, {}),
            **payload,
            "event_type": event.type,
        }
    elif event.type in {
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.step.failed",
        "workflow.step.skipped",
    }:
        key = str(
            payload.get("workflow_step_key")
            or payload.get("workflow_step_id")
            or event.sequence
        )
        tool_id = f"workflow:{key}"
        tools = next_projection.setdefault("tools", {})
        tools[tool_id] = {
            **tools.get(tool_id, {}),
            **payload,
            "event_type": event.type,
        }
    return next_projection


def compact_run_events(*, run_id, before, batch_size=500, include_active=False):
    """Fold and delete one consecutive batch, returning its durable snapshot."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least one")
    with transaction.atomic():
        run = Run.objects.select_for_update().filter(pk=run_id).first()
        if run is None:
            return None
        if not include_active and run.status not in TERMINAL_STATUSES:
            return None
        snapshot = RunEventSnapshot.objects.filter(run=run).first()
        through_sequence = snapshot.through_sequence if snapshot else 0
        projection = (
            deepcopy(snapshot.projection) if snapshot else empty_projection(run.id)
        )
        events = list(
            RunEvent.objects.filter(
                run=run,
                sequence__gt=through_sequence,
                created_at__lt=before,
            ).order_by("sequence")[:batch_size]
        )
        if not events:
            return None

        expected = through_sequence + 1
        for event in events:
            if event.sequence != expected:
                raise RuntimeError(
                    f"Run {run.id} event history has a gap at sequence {expected}"
                )
            projection = apply_projection_event(projection, event)
            expected += 1

        through_sequence = events[-1].sequence
        snapshot, _ = RunEventSnapshot.objects.update_or_create(
            run=run,
            defaults={
                "organization_id": run.organization_id,
                "through_sequence": through_sequence,
                "schema_version": 1,
                "projection": projection,
            },
        )
        RunEvent.objects.filter(run=run, sequence__lte=through_sequence).delete()
        return snapshot


def compact_eligible_runs(*, before, batch_size=500, run_id=None, organization_id=None):
    queryset = Run.objects.filter(status__in=TERMINAL_STATUSES)
    if organization_id is not None:
        queryset = queryset.filter(organization_id=organization_id)
    if run_id is not None:
        queryset = queryset.filter(pk=run_id)
    compacted = 0
    for candidate_id in queryset.values_list("id", flat=True).iterator():
        snapshot = compact_run_events(
            run_id=candidate_id,
            before=before,
            batch_size=batch_size,
        )
        if snapshot is not None:
            compacted += 1
    return compacted

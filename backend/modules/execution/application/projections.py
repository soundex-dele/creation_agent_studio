"""Project terminal Runs into domain read models without creating another executor."""
import json

from django.db import transaction

from modules.execution.models import Run


def _display_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _project_tool_calls(run):
    """Build the conversation read model from durable tool lifecycle events."""

    calls = {}
    order = []
    events = run.events.filter(
        type__in=("tool.started", "tool.completed", "tool.failed")
    ).order_by("sequence")
    for event in events:
        payload = event.payload or {}
        call_id = str(
            payload.get("tool_call_id") or payload.get("call_id") or event.sequence
        )
        if call_id not in calls:
            calls[call_id] = {
                "id": call_id,
                "name": str(payload.get("name") or payload.get("tool") or "tool"),
                "status": "running",
            }
            order.append(call_id)
        call = calls[call_id]
        if payload.get("name") or payload.get("tool"):
            call["name"] = str(payload.get("name") or payload.get("tool"))
        input_value = _display_value(payload.get("input"))
        if input_value is not None:
            call["input"] = input_value
        result_value = _display_value(payload.get("result", payload.get("output")))
        if result_value is not None:
            call["result"] = result_value
        if event.type == "tool.failed":
            call["status"] = "failed"
            error_message = payload.get("error_message")
            if error_message:
                call["error_message"] = str(error_message)
        elif event.type == "tool.completed":
            call["status"] = "completed"
    return [calls[call_id] for call_id in order]


def project_terminal_run(run_id, output):
    run = Run.objects.get(pk=run_id)
    if run.source_type != "conversation" or not run.source_id:
        return
    from apps.conversations.models import Conversation, Message

    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().filter(
            pk=run.source_id,
            organization_id=run.organization_id,
            user_id=run.owner_id,
        ).first()
        if conversation is None:
            return
        tool_calls = _project_tool_calls(run)
        metadata = {
            "run_id": str(run.id),
            "model": output.get("model") or "",
            "usage": output.get("usage") or {},
        }
        if tool_calls:
            metadata["agent"] = {"tool_calls": tool_calls}
        Message.objects.get_or_create(
            run=run,
            defaults={
                "conversation": conversation,
                "role": "assistant",
                "content": str(output.get("result") or ""),
                "metadata": metadata,
            },
        )

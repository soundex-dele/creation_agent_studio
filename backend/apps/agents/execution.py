"""Product adapter that executes an Agent through the durable Run protocol."""

from apps.enterprise.models import Organization
from core.llm.factory import build_agent_engine


def execute_agent_completion(run_payload, sink):
    snapshot = dict(run_payload.get("definition_snapshot") or {})
    definition = dict(snapshot.get("agent_definition") or {})
    model_config = dict(definition.get("model_config") or {})
    organization = Organization.objects.get(pk=run_payload["organization_id"])
    engine = build_agent_engine(
        organization,
        model_config.get("model", ""),
        adapter_name=model_config.get("adapter", ""),
        working_directory=str((run_payload.get("input") or {}).get("working_directory") or ""),
    )
    input_data = dict(run_payload.get("input") or {})
    checkpoint = ((run_payload.get("checkpoint") or {}).get("metadata") or {}).get(
        "checkpoint"
    ) or {}
    messages = checkpoint.get("messages")
    if not isinstance(messages, list):
        history = input_data.get("messages")
        if not isinstance(history, list):
            history = [{
                "role": "user",
                "content": str(input_data.get("message") or input_data),
            }]
        messages = [
            {"role": "system", "content": str(definition.get("system_prompt") or "")},
            *history,
        ]

    resume_command = run_payload.get("resume_command") or {}
    governance = snapshot.get("governance") or {}
    approval_decision = ""
    if resume_command:
        command_type = resume_command.get("type")
        command_payload = resume_command.get("payload") or {}
        if command_type == "answer":
            answer = command_payload.get("text")
            if not answer:
                answer = ", ".join(command_payload.get("selections") or [])
            messages = [*messages, {"role": "user", "content": str(answer or "")}]
        elif command_type == "grant_permission":
            approval_decision = "grant"
        elif command_type == "deny_permission":
            approval_decision = "deny"
            messages = [
                *messages,
                {"role": "user", "content": "The requested permission was denied."},
            ]

    emitted_output = False

    def emit_runtime_event(event_type, payload):
        nonlocal emitted_output
        if event_type in {"output.delta", "output.snapshot"}:
            emitted_output = True
        sink.emit(event_type, payload)

    response = engine.complete(
        messages,
        approval_decision=approval_decision,
        require_tool_approval=bool(governance.get("require_tool_approval", False)),
        on_event=emit_runtime_event,
    )
    if response.input_request:
        request = dict(response.input_request)
        input_kind = request.pop("input_kind", "answer")
        expires_in_seconds = int(request.pop("expires_in_seconds", 86400))
        sink.request_input(
            input_kind=input_kind,
            request_payload=request,
            checkpoint={"messages": messages},
            expires_in_seconds=expires_in_seconds,
        )
    if not response.success:
        raise RuntimeError(response.error or "Agent execution failed")
    # Adapters that do not expose incremental events still get the canonical
    # output event. Streaming adapters have already emitted their deltas.
    if response.content and not emitted_output:
        sink.emit("output.delta", {"text": response.content})
    output = {
        "result": response.content,
        "model": response.model,
        "usage": response.usage.model_dump(),
    }
    sink.emit("output.snapshot", output)
    return output

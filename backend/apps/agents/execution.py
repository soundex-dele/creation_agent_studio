"""Product adapter that executes an Agent through the durable Run protocol."""
import logging
import time

from apps.enterprise.models import Organization
from core.llm.factory import build_agent_engine
logger = logging.getLogger(__name__)


def execute_agent_completion(run_payload, sink):
    started = time.perf_counter()
    run_id = run_payload.get("run_id", "unknown")
    logger.info("chat_latency stage=agent_entered run_id=%s", run_id)
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
    provider_name = str(
        getattr(engine, "adapter_name", "") or model_config.get("adapter") or ""
    )
    input_data = dict(run_payload.get("input") or {})
    checkpoint = ((run_payload.get("checkpoint") or {}).get("metadata") or {}).get(
        "checkpoint"
    ) or {}
    agent_thread = dict(
        checkpoint.get("agent_thread") or input_data.get("agent_thread") or {}
    )
    thread_id = ""
    if agent_thread.get("provider") == provider_name:
        thread_id = str(agent_thread.get("id") or "")
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
            if thread_id:
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "The requested permission was granted. "
                            "Retry the requested operation."
                        ),
                    },
                ]
        elif command_type == "deny_permission":
            approval_decision = "deny"
            messages = [
                *messages,
                {"role": "user", "content": "The requested permission was denied."},
            ]

    emitted_output = False
    seen_events = set()

    def emit_runtime_event(event_type, payload):
        nonlocal emitted_output
        if event_type not in seen_events:
            seen_events.add(event_type)
            logger.info(
                "chat_latency stage=first_engine_event run_id=%s type=%s elapsed_ms=%.1f",
                run_id, event_type, (time.perf_counter() - started) * 1000,
            )
        if event_type in {"output.delta", "output.snapshot"}:
            emitted_output = True
        sink.emit(event_type, payload)

    logger.info(
        "chat_latency stage=engine_call run_id=%s setup_ms=%.1f messages=%d",
        run_id, (time.perf_counter() - started) * 1000, len(messages),
    )
    response = engine.complete(
        messages,
        approval_decision=approval_decision,
        require_tool_approval=bool(governance.get("require_tool_approval", False)),
        thread_id=thread_id,
        on_event=emit_runtime_event,
    )
    logger.info(
        "chat_latency stage=engine_returned run_id=%s elapsed_ms=%.1f success=%s streamed=%s",
        run_id, (time.perf_counter() - started) * 1000, response.success, emitted_output,
    )
    if response.input_request:
        request = dict(response.input_request)
        input_kind = request.pop("input_kind", "answer")
        expires_in_seconds = int(request.pop("expires_in_seconds", 86400))
        checkpoint_data = {"messages": messages}
        if response.thread_id and provider_name:
            checkpoint_data["agent_thread"] = {
                "provider": provider_name,
                "id": response.thread_id,
            }
        sink.request_input(
            input_kind=input_kind,
            request_payload=request,
            checkpoint=checkpoint_data,
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
    if response.thread_id and provider_name:
        output["agent_thread"] = {
            "provider": provider_name,
            "id": response.thread_id,
        }
    else:
        output["agent_thread"] = {}
    return output

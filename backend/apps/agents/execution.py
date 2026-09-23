"""Product adapter that executes an Agent through the durable Run protocol."""
import logging
import time

from apps.enterprise.models import Organization
from core.llm.factory import build_agent_engine
from apps.workflows.artifacts import (
    artifact_instructions, collect_workflow_artifacts, workflow_artifact_baseline,
    publish_workflow_artifacts,
)
logger = logging.getLogger(__name__)

OUTPUT_DELTA_FLUSH_CHARS = 256
OUTPUT_DELTA_FLUSH_SECONDS = 0.05


def _resume_answer_message(command_payload, input_request):
    answers = command_payload.get("answers")
    if isinstance(answers, dict) and answers:
        question_by_id = {
            str(item.get("id") or ""): str(item.get("question") or "")
            for item in input_request.get("questions") or []
            if isinstance(item, dict)
        }
        lines = []
        for question_id, answer_payload in answers.items():
            if isinstance(answer_payload, dict):
                values = answer_payload.get("answers") or []
            else:
                values = answer_payload
            if not isinstance(values, list):
                values = [values]
            answer_text = ", ".join(
                str(value) for value in values if value not in (None, "")
            )
            if not answer_text:
                continue
            question = question_by_id.get(str(question_id)) or str(question_id)
            lines.append(f"- {question}: {answer_text}")
        if lines:
            return (
                "Answers to the questions you asked:\n"
                + "\n".join(lines)
                + "\nContinue the previous task using these answers."
            )
    answer = command_payload.get("text")
    if not answer:
        answer = ", ".join(command_payload.get("selections") or [])
    return str(answer or "")


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
    attachments = input_data.get("attachments")
    if not isinstance(attachments, list):
        attachments = []
    image_paths = [
        str(item.get("path"))
        for item in attachments
        if isinstance(item, dict) and item.get("path")
    ]
    if image_paths and provider_name != "codex":
        raise RuntimeError(
            "Image attachments are supported only by the Codex adapter; "
            "GraphFlow does not support image input."
        )
    skills = input_data.get("skills")
    if not isinstance(skills, list):
        skills = []
    checkpoint = ((run_payload.get("checkpoint") or {}).get("metadata") or {}).get(
        "checkpoint"
    ) or {}
    artifact_baseline = checkpoint.get("workflow_artifact_baseline")
    if artifact_baseline is None:
        artifact_baseline = workflow_artifact_baseline(snapshot, input_data.get("working_directory"))
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
        instructions = artifact_instructions(snapshot)
        if instructions:
            messages.append({"role": "user", "content": instructions})

    resume_command = run_payload.get("resume_command") or {}
    governance = snapshot.get("governance") or {}
    approval_decision = ""
    if resume_command:
        command_type = resume_command.get("type")
        command_payload = resume_command.get("payload") or {}
        if command_type == "answer":
            answer = _resume_answer_message(
                command_payload,
                checkpoint.get("input_request") or {},
            )
            messages = [*messages, {"role": "user", "content": answer}]
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
    pending_output = []
    pending_output_chars = 0
    last_output_flush = time.perf_counter()

    def flush_output_delta():
        nonlocal pending_output, pending_output_chars, last_output_flush
        if not pending_output:
            return
        sink.emit("output.delta", {"text": "".join(pending_output)})
        pending_output = []
        pending_output_chars = 0
        last_output_flush = time.perf_counter()

    def emit_runtime_event(event_type, payload):
        nonlocal emitted_output, pending_output_chars
        if event_type not in seen_events:
            seen_events.add(event_type)
            logger.info(
                "chat_latency stage=first_engine_event run_id=%s type=%s elapsed_ms=%.1f",
                run_id, event_type, (time.perf_counter() - started) * 1000,
            )
        if event_type == "output.delta":
            emitted_output = True
            text = str(payload.get("text") or "")
            if not text:
                return
            pending_output.append(text)
            pending_output_chars += len(text)
            if (
                pending_output_chars >= OUTPUT_DELTA_FLUSH_CHARS
                or time.perf_counter() - last_output_flush >= OUTPUT_DELTA_FLUSH_SECONDS
            ):
                flush_output_delta()
            return
        flush_output_delta()
        if event_type == "output.snapshot":
            emitted_output = True
        sink.emit(event_type, payload)

    logger.info(
        "chat_latency stage=engine_call run_id=%s setup_ms=%.1f messages=%d",
        run_id, (time.perf_counter() - started) * 1000, len(messages),
    )
    try:
        response = engine.complete(
            messages,
            approval_decision=approval_decision,
            require_tool_approval=bool(governance.get("require_tool_approval", False)),
            permission_mode=input_data.get("permission_mode"),
            collaboration_mode=input_data.get("collaboration_mode"),
            thread_id=thread_id,
            skills=skills,
            image_paths=[] if resume_command else image_paths,
            on_event=emit_runtime_event,
            cancelled=lambda: sink.cancelled,
        )
    except Exception:
        if sink.cancelled:
            return {}
        raise
    flush_output_delta()
    logger.info(
        "chat_latency stage=engine_returned run_id=%s elapsed_ms=%.1f success=%s streamed=%s",
        run_id, (time.perf_counter() - started) * 1000, response.success, emitted_output,
    )
    if response.input_request:
        checkpoint_request = dict(response.input_request)
        request = dict(checkpoint_request)
        input_kind = request.pop("input_kind", "answer")
        expires_in_seconds = int(request.pop("expires_in_seconds", 86400))
        checkpoint_data = {
            "messages": messages,
            "input_request": checkpoint_request,
        }
        if artifact_baseline:
            checkpoint_data["workflow_artifact_baseline"] = artifact_baseline
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
    if sink.cancelled:
        return {}
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
        "loaded_skills": [
            str(item.get("display_name") or item.get("name") or "")
            for item in skills
            if (
                isinstance(item, dict)
                and item.get("path")
                and (item.get("display_name") or item.get("name"))
            )
        ],
    }
    artifacts = collect_workflow_artifacts(snapshot, input_data.get("working_directory"), artifact_baseline)
    if artifacts:
        output["artifacts"] = artifacts
        publish_workflow_artifacts(artifacts, sink)
    sink.emit("output.snapshot", output)
    if response.thread_id and provider_name:
        output["agent_thread"] = {
            "provider": provider_name,
            "id": response.thread_id,
        }
    else:
        output["agent_thread"] = {}
    return output

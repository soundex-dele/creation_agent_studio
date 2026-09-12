"""Built-in adapters for the unified durable execution plane."""
import os
import importlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v",
}

def execute_batch_transcribe(run_payload, sink):
    """Execute batch transcription through the durable Run API."""
    config = {
        **dict(run_payload.get("effective_config") or {}),
        **dict(run_payload.get("input") or {}),
    }
    folder_path = Path(config.get("folder", "")).expanduser().resolve(strict=False)
    allowed_roots = [
        Path(root).expanduser().resolve(strict=False)
        for root in run_payload.get("allowed_roots", [])
    ]
    if not allowed_roots or not any(
        folder_path == root or root in folder_path.parents for root in allowed_roots
    ):
        raise PermissionError("Batch transcription folder is outside runtime roots.")
    folder = str(folder_path)
    model = config.get("model", "base")
    language = config.get("language") or None
    output_dir = config.get("output_dir") or os.path.join(folder, "transcripts")
    videos = sorted(
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS
    ) if os.path.isdir(folder) else []
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("批量转录功能不可用：未安装 faster-whisper。") from exc
    os.makedirs(output_dir, exist_ok=True)
    whisper = WhisperModel(model)
    total = len(videos)
    outputs = []
    for index, video in enumerate(videos, start=1):
        if sink.cancelled:
            return {"status": "cancelled", "files": outputs}
        name = os.path.basename(video)
        sink.emit("tool.started", {
            "tool_call_id": str(index), "name": "transcribe", "file": name,
        })
        segments, info = whisper.transcribe(video, language=language)
        target = os.path.join(output_dir, f"{Path(video).stem}.txt")
        with open(target, "w", encoding="utf-8") as handle:
            for segment in segments:
                handle.write(segment.text.strip() + "\n")
        outputs.append(target)
        sink.emit("tool.completed", {
            "tool_call_id": str(index), "name": "transcribe", "file": name,
            "output": target, "language": info.language,
        })
        sink.emit("progress.updated", {"current": index, "total": total})
    return {"status": "completed", "files": outputs}


def execute_agent_completion(run_payload, sink):
    """Execute a snapshotted Agent definition as a durable Run."""
    from apps.enterprise.models import Organization
    from core.llm.factory import build_agent_engine

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

    response = engine.complete(messages, approval_decision=approval_decision)
    if response.input_request:
        request = dict(response.input_request)
        input_kind = request.pop("input_kind", "answer")
        sink.request_input(
            input_kind=input_kind,
            request_payload=request,
            checkpoint={"messages": messages},
            expires_in_seconds=int(request.pop("expires_in_seconds", 86400)),
        )
    if not response.success:
        raise RuntimeError(response.error or "Agent execution failed")
    sink.emit("output.delta", {"text": response.content})
    output = {
        "result": response.content,
        "model": response.model,
        "usage": response.usage.model_dump(),
    }
    sink.emit("output.snapshot", output)
    return output


class _WorkflowSink:
    def __init__(self, sink, step):
        self._sink = sink
        self._step = step

    @property
    def cancelled(self):
        return self._sink.cancelled

    def emit(self, event_type, payload):
        self._sink.emit(event_type, {
            "workflow_step_id": self._step["id"],
            "workflow_step_key": self._step["key"],
            "workflow_step_name": self._step["name"],
            **dict(payload or {}),
        })


def _value_at_path(value, path):
    for segment in str(path or "").split("."):
        if not segment:
            continue
        if not isinstance(value, dict) or segment not in value:
            return None, False
        value = value[segment]
    return value, True


def _condition_matches(condition, workflow_input, results):
    if not condition:
        return True
    if condition.get("source") == "dependency":
        source = results.get(condition.get("step"), {}).get("output", {})
    else:
        source = workflow_input
    actual, exists = _value_at_path(source, condition.get("path", ""))
    operator = condition.get("operator", "truthy")
    expected = condition.get("value")
    if operator == "exists":
        return exists
    if operator == "truthy":
        return bool(actual) if exists else False
    if operator == "equals":
        return exists and actual == expected
    if operator == "not_equals":
        return not exists or actual != expected
    if operator == "in":
        return exists and isinstance(expected, list) and actual in expected
    raise RuntimeError(f"Unsupported workflow condition operator: {operator}")


def _load_workflow_adapter(step, settings):
    entrypoint = settings.EXECUTION_CHILD_ADAPTERS.get(
        step["executor_kind"], {}
    ).get(step["executor_key"])
    if not entrypoint or step["executor_kind"] == "workflow":
        raise RuntimeError(
            f"Workflow step executor is unavailable: {step['executor_kind']}/{step['executor_key']}"
        )
    module_name, attribute_name = entrypoint.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute_name)


def _execute_workflow_step(step, run_payload, workflow_input, dependency_results, sink, settings):
    adapter = _load_workflow_adapter(step, settings)
    definition_snapshot = dict(step)
    dependencies = (step.get("content") or {}).get("dependencies") or {}
    default_agents = [
        value for value in dependencies.get("agents", []) if value.get("is_default")
    ]
    if default_agents:
        definition_snapshot["agent_definition"] = default_agents[0].get("definition") or {}
    step_sink = _WorkflowSink(sink, step)
    max_attempts = int(step.get("max_attempts") or 1)
    for attempt_no in range(1, max_attempts + 1):
        if sink.cancelled:
            return {"status": "cancelled"}
        step_sink.emit("workflow.step.started", {
            "attempt_no": attempt_no,
            "max_attempts": max_attempts,
        })
        try:
            output = adapter({
                **run_payload,
                "definition_snapshot": definition_snapshot,
                "effective_config": step.get("effective_config") or {},
                "input": {
                    **workflow_input,
                    "dependency_outputs": {
                        key: value.get("output", {})
                        for key, value in dependency_results.items()
                    },
                },
            }, step_sink) or {}
            step_sink.emit("workflow.step.completed", {
                "attempt_no": attempt_no,
                "output": output,
            })
            return {"status": "completed", "attempts": attempt_no, "output": output}
        except Exception as exc:
            retrying = attempt_no < max_attempts
            step_sink.emit("workflow.step.failed", {
                "attempt_no": attempt_no,
                "error": str(exc)[:1000],
                "retrying": retrying,
            })
            if not retrying:
                raise
    raise RuntimeError(f"Workflow step exhausted attempts: {step['key']}")


def execute_workflow(run_payload, sink):
    """Execute the single canonical workflow DAG with bounded parallelism."""
    from django.conf import settings

    steps = list((run_payload.get("definition_snapshot") or {}).get("workflow_steps") or [])
    by_key = {step["key"]: step for step in steps}
    if len(by_key) != len(steps):
        raise RuntimeError("Workflow snapshot contains duplicate step keys")
    unknown_dependencies = {
        dependency
        for step in steps
        for dependency in (step.get("depends_on") or [])
        if dependency not in by_key
    }
    if unknown_dependencies:
        raise RuntimeError(
            f"Workflow snapshot contains unknown dependencies: {sorted(unknown_dependencies)}"
        )

    workflow_input = dict(run_payload.get("input") or {})
    results = {}
    pending = set(by_key)
    completed = 0
    max_parallelism = max(
        1, int(getattr(settings, "EXECUTION_WORKFLOW_MAX_PARALLELISM", 4))
    )
    while pending:
        if sink.cancelled:
            break
        ready = sorted(
            key for key in pending
            if set(by_key[key].get("depends_on") or []).issubset(results)
        )
        if not ready:
            raise RuntimeError("Workflow snapshot contains a dependency cycle")

        runnable = []
        for key in ready:
            step = by_key[key]
            dependencies = {
                dependency: results[dependency]
                for dependency in step.get("depends_on") or []
            }
            if _condition_matches(step.get("condition") or {}, workflow_input, results):
                runnable.append((key, step, dependencies))
            else:
                results[key] = {"status": "skipped", "attempts": 0, "output": {}}
                _WorkflowSink(sink, step).emit("workflow.step.skipped", {
                    "condition": step.get("condition") or {},
                })
                pending.remove(key)
                completed += 1
                sink.emit("progress.updated", {"current": completed, "total": len(steps)})

        failures = []
        with ThreadPoolExecutor(max_workers=min(max_parallelism, max(1, len(runnable)))) as pool:
            futures = {
                pool.submit(
                    _execute_workflow_step,
                    step,
                    run_payload,
                    workflow_input,
                    dependencies,
                    sink,
                    settings,
                ): key
                for key, step, dependencies in runnable
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as exc:
                    failures.append((key, exc))
                pending.remove(key)
                completed += 1
                sink.emit("progress.updated", {"current": completed, "total": len(steps)})
        if failures:
            key, error = failures[0]
            raise RuntimeError(f"Workflow step {key} failed: {error}") from error

    ordered_results = [
        {"step_id": step["id"], "step_key": step["key"], **results[step["key"]]}
        for step in steps
        if step["key"] in results
    ]
    status = "cancelled" if sink.cancelled else "completed"
    return {"status": status, "steps": ordered_results}

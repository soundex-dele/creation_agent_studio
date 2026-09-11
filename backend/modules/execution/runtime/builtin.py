"""Built-in adapters for the unified durable execution plane."""
import os
import importlib
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
    history = input_data.get("messages")
    if not isinstance(history, list):
        history = [{"role": "user", "content": str(input_data.get("message") or input_data)}]
    messages = [
        {"role": "system", "content": str(definition.get("system_prompt") or "")},
        *history,
    ]
    response = engine.complete(messages)
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
            "workflow_step_name": self._step["name"],
            **dict(payload or {}),
        })


def execute_workflow(run_payload, sink):
    """Execute snapshotted workflow steps through the same adapter registry."""
    from django.conf import settings

    steps = list((run_payload.get("definition_snapshot") or {}).get("workflow_steps") or [])
    results = []
    current_input = dict(run_payload.get("input") or {})
    for index, step in enumerate(steps, start=1):
        if sink.cancelled:
            return {"status": "cancelled", "steps": results}
        entrypoint = settings.EXECUTION_CHILD_ADAPTERS.get(
            step["executor_kind"], {}
        ).get(step["executor_key"])
        if not entrypoint or step["executor_kind"] == "workflow":
            raise RuntimeError(
                f"Workflow step executor is unavailable: {step['executor_kind']}/{step['executor_key']}"
            )
        module_name, attribute_name = entrypoint.split(":", 1)
        adapter = getattr(importlib.import_module(module_name), attribute_name)
        definition_snapshot = dict(step)
        dependencies = (step.get("content") or {}).get("dependencies") or {}
        default_agents = [
            value for value in dependencies.get("agents", [])
            if value.get("is_default")
        ]
        if default_agents:
            definition_snapshot["agent_definition"] = default_agents[0].get("definition") or {}
        output = adapter({
            **run_payload,
            "definition_snapshot": definition_snapshot,
            "effective_config": step.get("effective_config") or {},
            "input": {**current_input, "previous_output": results[-1] if results else None},
        }, _WorkflowSink(sink, step))
        results.append({"step_id": step["id"], "output": output or {}})
        sink.emit("progress.updated", {"current": index, "total": len(steps)})
    return {"status": "completed", "steps": results}

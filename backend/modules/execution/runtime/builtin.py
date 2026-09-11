"""Built-in adapters for the unified durable execution plane."""
import os
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v",
}

BatchTranscribeCore = None


def _batch_transcribe_core():
    global BatchTranscribeCore
    if BatchTranscribeCore is None:
        try:
            from creation_core.transcribe import BatchTranscribeCore as core
        except ImportError as exc:
            raise RuntimeError(
                "批量转录功能不可用：未安装可选依赖 creation_core。"
            ) from exc
        BatchTranscribeCore = core
    return BatchTranscribeCore


class _LegacyEventTranslator:
    """Translate the old executor sink protocol into durable Run events."""

    def __init__(self, sink):
        self._sink = sink

    @property
    def cancelled(self):
        return self._sink.cancelled

    def emit(self, event_type, payload):
        payload = dict(payload or {})
        if event_type == "job.progress":
            self._sink.emit("progress.updated", payload)
        elif event_type == "item.state":
            status = payload.get("status")
            durable_type = {
                "done": "tool.completed",
                "completed": "tool.completed",
                "error": "tool.failed",
                "failed": "tool.failed",
            }.get(status, "tool.started")
            self._sink.emit(
                durable_type,
                {
                    "tool_call_id": str(payload.get("id") or ""),
                    "name": payload.get("name") or "batch-transcribe-item",
                    **payload,
                },
            )
        elif event_type == "log":
            self._sink.emit(
                "output.delta",
                {"text": f"{payload.get('msg', '')}\n", "level": payload.get("level")},
            )


def execute_batch_transcribe(run_payload, sink):
    """Execute batch transcription through the durable Run API."""
    config = dict(run_payload.get("input") or {})
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
    core = _batch_transcribe_core()(
        videos,
        output_dir,
        model_size=model,
        language=language,
    )
    core.run(_LegacyEventTranslator(sink))
    return {"status": "completed"}

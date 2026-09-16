"""Durable execution adapter for batch transcription."""

import os
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v",
}


def _is_within_allowed_roots(path, allowed_roots):
    return any(path == root or root in path.parents for root in allowed_roots)


def execute_batch_transcribe(run_payload, sink):
    config = {
        **dict(run_payload.get("effective_config") or {}),
        **dict(run_payload.get("input") or {}),
    }
    folder_path = Path(config.get("folder", "")).expanduser().resolve(strict=False)
    allowed_roots = [
        Path(root).expanduser().resolve(strict=False)
        for root in run_payload.get("allowed_roots", [])
    ]
    allow_all_paths = bool(run_payload.get("allow_all_paths", False))
    if not allow_all_paths and (
        not allowed_roots or not _is_within_allowed_roots(folder_path, allowed_roots)
    ):
        raise PermissionError("Batch transcription folder is outside runtime roots.")
    model = config.get("model", "base")
    language = config.get("language") or None
    output_path = Path(
        config.get("output_dir") or folder_path / "transcripts"
    ).expanduser().resolve(strict=False)
    if not allow_all_paths and not _is_within_allowed_roots(output_path, allowed_roots):
        raise PermissionError("Batch transcription output is outside runtime roots.")
    output_dir = str(output_path)
    videos = sorted(
        str(path)
        for item in folder_path.iterdir()
        if item.is_file()
        and item.suffix.lower() in VIDEO_EXTENSIONS
        and (
            allow_all_paths
            or _is_within_allowed_roots(path := item.resolve(strict=False), allowed_roots)
        )
    ) if folder_path.is_dir() else []
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
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            for segment in segments:
                handle.write(segment.text.strip() + "\n")
        outputs.append(target)
        if hasattr(sink, "create_artifact"):
            sink.create_artifact(
                kind="transcript",
                filename=Path(target).name,
                content=Path(target).read_bytes(),
                mime_type="text/plain; charset=utf-8",
                metadata={"source_file": name, "language": info.language},
            )
        sink.emit("tool.completed", {
            "tool_call_id": str(index), "name": "transcribe", "file": name,
            "output": target, "language": info.language,
        })
        sink.emit("progress.updated", {"current": index, "total": total})
    return {"status": "completed", "files": outputs}

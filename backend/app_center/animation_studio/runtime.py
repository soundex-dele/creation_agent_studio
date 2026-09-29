"""Two durable operations: build an HTML preview, or render an immutable version."""
import io
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from core.agent_engine.adapters.codex import CodexAdapter
from apps.enterprise.services import enforce_member_token_quota, record_usage
from modules.execution.models import Run
from modules.execution.infrastructure.artifacts import get_artifact_storage, open_artifact
from modules.tenancy.database import tenant_database_context
from .backend.access import application_for, assets_for, generation_for
from .backend.serializers import AnimationInputSerializer
from .backend.media import probe

PACKAGE = Path(__file__).resolve().parent
ENGINE = PACKAGE / "engine"
MAX_ARCHIVE = 120 * 1024 * 1024
logger = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


class AnimationBuildError(RuntimeError):
    def __init__(self, message, *, code="scene_build_error", retryable=True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def build_error(log, workspace):
    sanitized = log.replace(str(workspace), "<project>").replace(str(ENGINE), "<engine>")
    for line in reversed(sanitized.splitlines()):
        if line.startswith("ANIMATION_BUILD_ERROR "):
            try:
                data = json.loads(line.removeprefix("ANIMATION_BUILD_ERROR "))
                if isinstance(data, dict) and isinstance(data.get("message"), str):
                    message = data["message"].replace(str(workspace), "<project>").replace(str(ENGINE), "<engine>")
                    return AnimationBuildError(message, code=data.get("code", "scene_build_error"),
                                               retryable=data.get("retryable") is not False)
            except ValueError:
                pass
    return AnimationBuildError(sanitized)


def check_cancel(sink):
    if sink.cancelled:
        raise Cancelled()


def report_build_failure(sink, error, attempt, context=None):
    check_cancel(sink)
    sink.emit("progress.updated", {
        **(context or {}), "stage": "build_failed", "attempt": attempt,
        "error_message": str(error)[-4000:],
        "error_code": getattr(error, "code", "scene_build_error"),
        "will_retry": attempt < 3 and getattr(error, "retryable", True),
    })


def require_engine():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("动画引擎无法启动：未找到 Node.js，请安装 Node.js 20+ 并确保任务进程的 PATH 可访问 node。")
    if not (ENGINE / "node_modules" / "remotion" / "package.json").is_file():
        raise RuntimeError(
            "动画引擎依赖未安装，请在仓库根目录执行 "
            "npm ci --prefix backend/app_center/animation_studio/engine，随后执行 "
            "npm run browser --prefix backend/app_center/animation_studio/engine，再重新生成。"
        )
    return node


def ai_progress(sink, context):
    """Report output activity without publishing generated source or reasoning."""
    characters = 0
    last_emit = None

    def on_event(event_type, payload):
        nonlocal characters, last_emit
        if event_type not in ("output.delta", "output.snapshot"):
            return
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            return
        characters = len(text) if event_type == "output.snapshot" else characters + len(text)
        now = time.monotonic()
        if last_emit is None or now - last_emit >= 2:
            check_cancel(sink)
            sink.emit("progress.updated", {**context, "activity": "responding", "characters": characters})
            last_emit = now

    return on_event


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def run_process(arguments, workspace, sink, timeout=300):
    check_cancel(sink)
    # Log to disk rather than PIPE, so large compiler output cannot deadlock cancellation.
    log = Path(workspace) / "build.log"
    with log.open("w+b") as output:
        process = subprocess.Popen(arguments, cwd=ENGINE, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                check_cancel(sink)
                if time.monotonic() > deadline:
                    raise TimeoutError("动画任务超时，可稍后重试或缩短动画。")
                time.sleep(0.15)
            output.seek(0, 2)
            output.seek(max(0, output.tell() - 16000))
            tail = output.read().decode("utf-8", errors="replace")
            if process.returncode:
                raise build_error(tail, workspace)
        finally:
            stop_process(process)
    check_cancel(sink)


def read_archive(artifact, workspace):
    with open_artifact(artifact) as handle:
        content = handle.read(MAX_ARCHIVE + 1)
    if len(content) > MAX_ARCHIVE:
        raise RuntimeError("源码归档超过大小限制。")
    # Only recover authored source and data. Never restore executable build configuration.
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if sum(item.file_size for item in members) > MAX_ARCHIVE or len(members) > 150:
            raise RuntimeError("源码归档无效或过大。")
        for item in members:
            name = item.filename
            if name in ("Animation.tsx", "composition.json", "assets.json", "storyboard.md", "project.json") or (
                name.startswith("assets/") and name.count("/") == 1 and ".." not in name and "\\" not in name
            ):
                target = Path(workspace) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    if not all((Path(workspace) / name).is_file() for name in ("Animation.tsx", "composition.json", "assets.json")):
        raise RuntimeError("源码归档缺少必需文件。")


def archive_source(workspace):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("Animation.tsx", "composition.json", "assets.json", "storyboard.md", "project.json"):
            target = Path(workspace) / name
            if target.exists():
                archive.write(target, name)
        for target in sorted((Path(workspace) / "assets").glob("*")):
            if target.is_file():
                archive.write(target, "assets/" + target.name)
        for name in ("runner.mjs", "validate.mjs", "structured.mjs", "fonts.mjs", "preview.mjs", "dependencies.mjs", "package.json", "package-lock.json"):
            archive.write(ENGINE / name, name)
        archive.writestr("README.md", "# 动画源码\n\n需要 Node.js 20+、中文字体及 Chrome Headless Shell。\n\n"
            "1. npm ci\n2. npm run browser\n3. npm run preview（生成 out/preview.html，直接在浏览器打开）\n"
            "4. npm run render（生成 out/animation.mp4）\n\n"
            "修改 Animation.tsx 后重新构建。composition.json 保存画幅及帧数，assets/ 保存原始素材。\n")
    return buffer.getvalue()


def decode_result(text):
    from .json_output import decode_json_object
    result = decode_json_object(text)
    if not isinstance(result, dict) or not isinstance(result.get("source"), str) or not result["source"].strip():
        raise ValueError("AI 未返回有效动画源码。")
    if len(result["source"]) > 150000:
        raise ValueError("动画源码过长。")
    return {"source": result["source"], "title": str(result.get("title", "动画作品"))[:100],
            "storyboard": str(result.get("storyboard", ""))[:16000]}


def execute(payload, sink):
    try:
        return _execute(payload, sink)
    except Cancelled:
        return {"cancelled": True}


def _execute(payload, sink):
    check_cancel(sink)
    with tenant_database_context(payload["organization_id"]):
        run = Run.objects.for_organization(payload["organization_id"]).select_related("owner", "organization").get(pk=payload["run_id"])
        application = application_for(run.owner, run.organization_id, run.source_id)
        serializer = AnimationInputSerializer(data=run.input)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if "document" in values or values["action"] == "batch":
            from .studio_runtime import execute_studio
            return execute_studio(payload, sink, run, application, values)
        source = generation_for(run.owner, application, values["source_run_id"], ready=True, include_deleted=True) if values.get("source_run_id") else None
        source_artifact = source.artifacts.filter(kind="animation-source").first() if source else None
        asset_records = assets_for(run.owner, application, values.get("asset_ids", []))
        if values["action"] == "generate":
            enforce_member_token_quota(run.organization, run.owner)
    node = require_engine()
    root = Path(settings.AGENT_WORKSPACE_ROOT) / "animation-studio" / str(run.organization_id)
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f"{run.id}-", dir=root, ignore_cleanup_errors=True) as directory:
        workspace = Path(directory)
        if source_artifact:
            read_archive(source_artifact, workspace)
        if values["action"] == "export":
            if "export_options" in values:
                from .studio_runtime import export_format
                return export_format(workspace, node, sink, source.id, values["export_options"])
            return export_video(workspace, node, sink, source.id)
        previous_source = (workspace / "Animation.tsx").read_text("utf-8") if source else ""
        previous_story = (workspace / "storyboard.md").read_text("utf-8") if (workspace / "storyboard.md").exists() else ""
        manifest = json.loads((workspace / "assets.json").read_text("utf-8")) if source else []
        (workspace / "assets").mkdir(exist_ok=True)
        for item in asset_records:
            if any(entry["id"] == str(item.id) for entry in manifest):
                continue
            # Uploading a new recording replaces the inherited recording, not its old version.
            if item.duration is not None:
                manifest = [entry for entry in manifest if entry.get("duration") is None]
            suffix = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/mp4": "m4a"}[item.mime_type]
            filename = f"{item.id}.{suffix}"
            with get_artifact_storage().open(item.object_key) as handle:
                content = handle.read(50 * 1024 * 1024 + 1)
            if len(content) != item.size:
                raise RuntimeError("素材已损坏，请重新上传。")
            (workspace / "assets" / filename).write_bytes(content)
            manifest.append({"id": str(item.id), "file": filename, "name": item.name, "mime_type": item.mime_type, "duration": item.duration})
        if len(manifest) > 10 or sum((workspace / "assets" / item["file"]).stat().st_size for item in manifest) > 100 * 1024 * 1024:
            raise RuntimeError("当前版本最多包含 10 个素材，合计不能超过 100 MB。")
        # Remove superseded audio from the new snapshot only.
        active_files = {item["file"] for item in manifest}
        for item in (workspace / "assets").iterdir():
            if item.name not in active_files:
                item.unlink()
        audio = next((item for item in manifest if item.get("duration") is not None), None)
        width, height = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[values["aspect"]]
        config = {"width": width, "height": height, "fps": 30,
                  "durationInFrames": math.ceil((audio["duration"] if audio else values["duration"]) * 30),
                  "audioId": audio["id"] if audio else None}
        (workspace / "assets.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
        (workspace / "composition.json").write_text(json.dumps(config), "utf-8")
        messages = [{"role": "system", "content": (PACKAGE / "authoring.md").read_text("utf-8")},
                    {"role": "user", "content": json.dumps({"requirements": values, "composition": config,
                     "assets": manifest, "previous_source": previous_source, "previous_storyboard": previous_story}, ensure_ascii=False)}]
        result = None
        last_error = ""
        for attempt in range(3):
            check_cancel(sink)
            sink.emit("progress.updated", {"stage": "generating" if attempt == 0 else "repairing", "attempt": attempt + 1})
            response = CodexAdapter(model=(payload.get("effective_config") or {}).get("model")).complete(
                messages, working_directory=str(workspace), cancelled=lambda: sink.cancelled, timeout_seconds=600,
                on_event=ai_progress(sink, {"stage": "generating" if attempt == 0 else "repairing", "attempt": attempt + 1}))
            check_cancel(sink)
            with tenant_database_context(run.organization_id):
                record_usage(organization=run.organization, user=run.owner, resource_type="application", resource_id=str(application.id),
                             usage=response.usage.model_dump(), provider="codex", model=response.model)
            if not response.success:
                raise RuntimeError("AI 动画生成失败，请检查 Codex 登录、模型及网络配置后重试。")
            try:
                result = decode_result(response.content)
                (workspace / "Animation.tsx").write_text(result["source"], "utf-8")
                (workspace / "storyboard.md").write_text(result["storyboard"], "utf-8")
                sink.emit("progress.updated", {"stage": "building_preview"})
                run_process([node, str(ENGINE / "runner.mjs"), "preview", str(workspace)], workspace, sink)
                break
            except (ValueError, RuntimeError) as exc:
                report_build_failure(sink, exc, attempt + 1)
                if isinstance(exc, AnimationBuildError) and not exc.retryable:
                    sink.create_artifact(kind="animation-diagnostic", filename="build-error.txt", content=str(exc), mime_type="text/plain")
                    raise
                last_error = str(exc)[-4000:]
                messages.extend([{"role": "assistant", "content": response.content},
                                 {"role": "user", "content": f"修复以下构建错误，返回完整 JSON：\n{last_error}"}])
        else:
            if result:
                sink.create_artifact(kind="animation-diagnostic-source", filename="animation-incomplete.zip",
                    content=archive_source(workspace), mime_type="application/zip", metadata={"incomplete": True})
            sink.create_artifact(kind="animation-diagnostic", filename="build-error.txt", content=last_error, mime_type="text/plain")
            raise RuntimeError("动画预览构建失败，已尝试修复两次。请调整描述后重试；诊断文件已保存。")
        check_cancel(sink)
        sink.emit("progress.updated", {"stage": "saving"})
        metadata = {**config, "title": result["title"], "storyboard": result["storyboard"], "source_run_id": str(source.id) if source else None}
        sink.create_artifact(kind="animation-source", filename="animation-source.zip", content=archive_source(workspace), mime_type="application/zip", metadata=metadata)
        sink.create_artifact(kind="animation-preview", filename="preview.html", content=(workspace / "out" / "preview.html").read_bytes(), mime_type="text/html", metadata=metadata)
        return {"title": result["title"], "preview_ready": True, **config}


def export_video(workspace, node, sink, source_id):
    config = json.loads((workspace / "composition.json").read_text("utf-8"))
    sink.emit("progress.updated", {"stage": "rendering"})
    run_process([node, str(ENGINE / "runner.mjs"), "render", str(workspace)], workspace, sink, timeout=1200)
    video = workspace / "out" / "animation.mp4"
    info = probe(video)
    streams = info.get("streams", [])
    track = next((item for item in streams if item.get("codec_type") == "video"), {})
    expected = config["durationInFrames"] / config["fps"]
    if (track.get("codec_name") != "h264" or track.get("width") != config["width"] or track.get("height") != config["height"]
            or abs(float(info["format"].get("duration", 0)) - expected) > 0.15
            or ((config.get("audioId") or config.get("hasAudio")) and not any(item.get("codec_type") == "audio" for item in streams))):
        raise RuntimeError("导出视频的画幅、时长或录音校验失败，HTML 预览仍然可用。")
    run_process(["ffmpeg", "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"], workspace, sink, timeout=300)
    check_cancel(sink)
    sink.emit("progress.updated", {"stage": "saving"})
    metadata = {**config, "source_run_id": str(source_id), "duration": expected}
    sink.create_artifact(kind="animation-video", filename="animation.mp4", content=video.read_bytes(), mime_type="video/mp4", metadata=metadata)
    sink.create_artifact(kind="animation-cover", filename="cover.png", content=(workspace / "out" / "cover.png").read_bytes(), mime_type="image/png", metadata=metadata)
    return {"source_run_id": str(source_id), "export_ready": True, **config}

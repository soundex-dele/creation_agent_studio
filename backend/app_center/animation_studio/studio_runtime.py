import copy
import json
import math
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.enterprise.services import enforce_member_token_quota, record_usage
from core.agent_engine.adapters.codex import CodexAdapter
from core.transcription import transcribe_segments
from modules.execution.infrastructure.artifacts import get_artifact_storage
from .backend.documents import validate_document, asset_ids, scene
from .backend.projects import project_for, document_assets
from .backend.models import AnimationProject, AnimationVersion, AnimationAsset
from .backend.media import probe
from .runtime import ENGINE, PACKAGE, check_cancel, run_process, archive_source, export_video


def ask(run, application, payload, sink, system, content, workspace):
    check_cancel(sink)
    enforce_member_token_quota(run.organization, run.owner)
    response = CodexAdapter(model=(payload.get("effective_config") or {}).get("model")).complete(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(content, ensure_ascii=False)}],
        working_directory=str(workspace), cancelled=lambda: sink.cancelled, timeout_seconds=600)
    check_cancel(sink)
    record_usage(organization=run.organization, user=run.owner, resource_type="application", resource_id=str(application.id),
                 usage=response.usage.model_dump(), provider="codex", model=response.model)
    if not response.success: raise RuntimeError("AI 制作失败，请检查模型及网络设置。")
    text = response.content.strip()
    if text.startswith("```"): text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def storyboard(run, app, payload, sink, doc, workspace):
    sink.emit("progress.updated", {"stage": "storyboard"})
    previous = {}
    if doc.get("conversion_source"):
        from .backend.access import generation_for
        from .runtime import read_archive
        old = generation_for(run.owner, app, doc["conversion_source"], ready=True)
        folder = workspace / "original"; folder.mkdir(exist_ok=True)
        read_archive(old.artifacts.get(kind="animation-source"), folder)
        previous = {"source": (folder / "Animation.tsx").read_text("utf-8"), "storyboard": (folder / "storyboard.md").read_text("utf-8") if (folder / "storyboard.md").exists() else ""}
    result = ask(run, app, payload, sink,
        '你是动画分镜导演。只返回 JSON {"scenes":[{"title":"标题","body":"画面文案","narration":"旁白","description":"画面描述","frames":300}]}。总时长 150–3600 帧，30fps，最多30幕。保留用户事实、数字与限定，不编造数据。',
        {"prompt": doc["prompt"], "style": doc["style"], "aspect": doc["aspect"], "original_work": previous}, workspace)
    items = result.get("scenes", [])
    if not isinstance(items, list): raise RuntimeError("AI 分镜结果无效。")
    doc["scenes"] = [{**scene(), **{key: item[key] for key in ("title", "body", "narration", "description", "frames") if key in item}} for item in items]
    for item in doc["scenes"]: item["style"].update({k: v for k, v in doc.get("brand", {}).items() if k in ("color", "background", "font")})
    return validate_document(doc, complete=True)


def persist_result(run, project, values, doc, sink):
    check_cancel(sink)
    doc = validate_document(doc, complete=True)
    sink.create_artifact(kind="animation-document", filename="project.json", content=json.dumps(doc, ensure_ascii=False), mime_type="application/json", metadata={"schema_version": 2})
    changed = AnimationProject.objects.filter(pk=project.id, revision=values["draft_revision"]).update(
        draft=doc, revision=values["draft_revision"] + 1, updated_at=timezone.now())
    return {"project_id": str(project.id), "draft_applied": bool(changed), "title": project.title}


def execute_studio(payload, sink, run, app, values):
    if values["action"] == "batch":
        from .backend.batch import execute_batch
        return execute_batch(payload, sink, run, app, values)
    project = project_for(run.owner, app, values["project_id"])
    doc = copy.deepcopy(values["document"])
    document_assets(run.owner, app, doc)
    root = Path(settings.AGENT_WORKSPACE_ROOT) / "animation-studio" / str(run.organization_id)
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f"{run.id}-", dir=root, ignore_cleanup_errors=True) as directory:
        workspace = Path(directory)
        action = values["action"]
        if action == "storyboard" or (action == "generate" and not doc["scenes"]):
            doc = storyboard(run, app, payload, sink, doc, workspace)
        if action == "speech":
            from .speech import synthesize
            item = next(s for s in doc["scenes"] if s["id"] == values["scene_id"])
            text = item.get("narration", "").strip()
            if not text: raise RuntimeError("请先填写该场景的旁白。")
            sink.emit("progress.updated", {"stage": "speech"})
            audio = synthesize(app, text, values["voice"], values.get("speed", 1), cancelled=lambda: sink.cancelled)
            record_usage(organization=run.organization, user=run.owner, resource_type="application", resource_id=str(app.id),
                provider="volcengine-speech", model="doubao-tts", metadata={"characters": len(text), "audio_bytes": len(audio)})
            path = workspace / "speech.mp3"; path.write_bytes(audio)
            duration = float(probe(path)["format"]["duration"])
            if not math.isfinite(duration) or not 0 < duration <= 120: raise RuntimeError("配音时长超出限制。")
            frames = math.ceil(duration * 30)
            old_frames = item["frames"]
            item["frames"] = max(item["frames"], frames)
            if sum(s["frames"] for s in doc["scenes"]) > 3600: raise RuntimeError("配音后总时长超过120秒，请缩短旁白。")
            identifier = uuid.uuid4(); key = f"animation-studio/{app.organization_id}/{run.owner_id}/assets/{identifier}"
            check_cancel(sink)
            storage = get_artifact_storage(); storage.put(key, audio)
            try:
                AnimationAsset.objects.create(id=identifier, organization=app.organization, application=app, owner=run.owner,
                    name=(item["title"] + " · 配音.mp3")[:200], category="配音", object_key=key, mime_type="audio/mpeg", size=len(audio), duration=duration)
            except Exception:
                storage.delete(key); raise
            doc["audio"] = [t for t in doc["audio"] if not (t.get("scene_id") == item["id"] and t["role"] == "narration")]
            doc["audio"].append({"asset_id": str(identifier), "scene_id": item["id"], "role": "narration", "start": 0, "frames": frames, "volume": 1})
            offset = sum(s["frames"] for s in doc["scenes"][:doc["scenes"].index(item)])
            delta = item["frames"] - old_frames
            doc["subtitles"] = [{**s, "start": s["start"] + (delta if s["start"] >= offset + old_frames else 0), "end": s["end"] + (delta if s["start"] >= offset + old_frames else 0)} for s in doc["subtitles"] if not offset <= s["start"] < offset + old_frames]
            transcription = transcribe_segments(path, cancelled=lambda: sink.cancelled)
            doc["subtitles"].extend({"start": offset + math.floor(s["start"] * 30), "end": min(offset + frames, offset + math.ceil(s["end"] * 30)), "text": s["text"]} for s in transcription["segments"] if s["end"] > s["start"])
        elif action == "transcribe":
            asset = AnimationAsset.objects.for_organization(app.organization_id).get(id=values["asset_id"], application=app, owner=run.owner)
            if asset.duration is None: raise RuntimeError("请选择音频素材。")
            track = next((t for t in doc["audio"] if t["asset_id"] == str(asset.id)), None)
            if not track: raise RuntimeError("请先把录音添加到音轨。")
            path = workspace / "recording"
            with get_artifact_storage().open(asset.object_key) as handle: path.write_bytes(handle.read())
            sink.emit("progress.updated", {"stage": "transcribing"})
            result = transcribe_segments(path, cancelled=lambda: sink.cancelled)
            offset = track.get("start", 0)
            for s in doc["scenes"]:
                if s["id"] == track.get("scene_id"): break
                if track.get("scene_id"): offset += s["frames"]
            trim = track.get("trim_start", 0); total = sum(s["frames"] for s in doc["scenes"])
            doc["subtitles"] = [{"start": max(offset, offset + math.floor(s["start"] * 30) - trim), "end": min(total, offset + math.ceil(s["end"] * 30) - trim), "text": s["text"]} for s in result["segments"] if offset + math.ceil(s["end"]*30)-trim > offset and offset + math.floor(s["start"]*30)-trim < total]
        if action in ("generate", "scene"):
            node = shutil.which("node")
            if not node or not (ENGINE / "node_modules" / "remotion").exists(): raise RuntimeError("动画引擎未安装。")
            targets = [s for s in doc["scenes"] if (s["id"] == values.get("scene_id") if action == "scene" else not s.get("source") and not s.get("locked"))]
            for item in targets:
                sink.emit("progress.updated", {"stage": "generating", "scene_id": item["id"]})
                system = (PACKAGE / "authoring.md").read_text("utf-8") + '\n现在只生成一个独立场景。默认组件接收 {scene} props，标题、正文、素材及颜色必须读取 scene.title/body/assets/style；不要把这些可编辑内容写死。场景长度使用 scene.frames。不要生成旁白、字幕或场景排序。'
                content = {"scene": item, "requirements": values.get("instruction", doc["prompt"]), "aspect": doc["aspect"], "style": doc["style"]}
                last_error = ""
                for attempt in range(3):
                    result = ask(run, app, payload, sink, system, {**content, "build_error": last_error}, workspace)
                    source = result.get("source")
                    if not isinstance(source, str) or not source.strip(): raise RuntimeError("AI 没有返回场景源码。")
                    item["source"] = source
                    prepare(workspace, doc, run.owner, app)
                    try:
                        run_process([node, str(ENGINE / "runner.mjs"), "preview", str(workspace)], workspace, sink)
                        break
                    except RuntimeError as exc:
                        last_error = str(exc)[-4000:]
                else: raise RuntimeError("场景构建失败，已尝试修复两次。" + last_error)
            if action == "scene": doc["note"] = f"修改 {targets[0]['title']}：{values['instruction']}"[:1000]
            prepare(workspace, doc, run.owner, app)
            run_process([node, str(ENGINE / "runner.mjs"), "preview", str(workspace)], workspace, sink)
            if action == "generate":
                config = json.loads((workspace / "composition.json").read_text("utf-8"))
                metadata = {**config, "title": project.title, "storyboard": "\n".join(s["title"] for s in doc["scenes"])}
                check_cancel(sink)
                sink.create_artifact(kind="animation-source", filename="animation-source.zip", content=archive_source(workspace), mime_type="application/zip", metadata=metadata)
                sink.create_artifact(kind="animation-preview", filename="preview.html", content=(workspace / "out/preview.html").read_bytes(), mime_type="text/html", metadata=metadata)
                run_process([node, str(ENGINE / "runner.mjs"), "cover", str(workspace)], workspace, sink)
                sink.create_artifact(kind="animation-cover", filename="cover.png", content=(workspace / "out/cover.png").read_bytes(), mime_type="image/png", metadata=metadata)
                # The version is published only when its Run succeeds; never rewrite completed versions.
                AnimationVersion.objects.filter(run=run, run__status="running").update(document=doc)
        return {**persist_result(run, project, values, doc, sink), "preview_ready": action == "generate"}


def prepare(workspace, doc, user, app):
    doc = validate_document(doc, complete=True)
    records = document_assets(user, app, doc)
    folder = workspace / "assets"; folder.mkdir(exist_ok=True)
    manifest = []
    for item in records:
        suffix = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/mp4": "m4a"}[item.mime_type]
        filename = f"{item.id}.{suffix}"
        with get_artifact_storage().open(item.object_key) as handle: content = handle.read(50 * 1024 * 1024 + 1)
        if len(content) != item.size: raise RuntimeError("素材大小校验失败。")
        (folder / filename).write_bytes(content)
        manifest.append({"id": str(item.id), "file": filename, "mime_type": item.mime_type, "name": item.name, "duration": item.duration})
    total = sum(s["frames"] for s in doc["scenes"])
    offsets = {}; cursor = 0
    for s in doc["scenes"]: offsets[s["id"]] = cursor; cursor += s["frames"]
    by_id = {str(a.id): a for a in records}
    for track in doc["audio"]:
        item = by_id.get(track.get("asset_id"))
        if not item or item.duration is None: raise RuntimeError("音轨素材不是音频。")
        available = math.ceil(item.duration * 30) - track.get("trim_start", 0)
        if available <= 0: raise RuntimeError("音轨裁剪起点超出素材。")
        frames = track.get("frames", available)
        if track["role"] == "narration" and (frames < available or offsets.get(track.get("scene_id"), 0) + track.get("start", 0) + available > total):
            raise RuntimeError("旁白长度超过场景或工程，请延长分镜以保留完整旁白。")
        track["clip_frames"] = min(frames, available)
    width, height = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[doc["aspect"]]
    config = {"schema_version": 2, "width": width, "height": height, "fps": 30, "durationInFrames": total, "audioId": None, "hasAudio": bool(doc["audio"])}
    for filename, value in (("composition.json", config), ("project.json", doc), ("assets.json", manifest)):
        (workspace / filename).write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    (workspace / "storyboard.md").write_text("\n".join(s["title"] + "\n" + s.get("description", "") for s in doc["scenes"]), "utf-8")


def subtitle_text(doc, format):
    def stamp(frame):
        ms = round(frame / 30 * 1000); hours, ms = divmod(ms, 3600000); minutes, ms = divmod(ms, 60000); seconds, ms = divmod(ms, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02}{',' if format == 'srt' else '.'}{ms:03}"
    blocks = [f"{i+1}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}\n" for i, s in enumerate(sorted(doc.get("subtitles", []), key=lambda s: s["start"]))]
    return ("WEBVTT\n\n" if format == "vtt" else "") + "\n".join(blocks)


def export_format(workspace, node, sink, source_id, options):
    config_path = workspace / "composition.json"; config = json.loads(config_path.read_text("utf-8"))
    project_path = workspace / "project.json"
    doc = json.loads(project_path.read_text("utf-8")) if project_path.exists() else {}
    format = options["format"]
    if options["cover_frame"] >= config["durationInFrames"]: raise RuntimeError("封面时间超出动画长度。")
    if format in ("srt", "vtt"):
        if not doc.get("subtitles"): raise RuntimeError("该版本还没有字幕，请先识别或添加字幕。")
        sink.create_artifact(kind="animation-subtitles", filename=f"subtitles.{format}", content=subtitle_text(doc, format), mime_type="text/vtt" if format == "vtt" else "application/x-subrip", metadata={"format": format})
    else:
        if options["resolution"] == 720:
            config["width"] = round(config["width"] * 2 / 3); config["height"] = round(config["height"] * 2 / 3)
            if doc:
                doc["subtitle_style"]["size"] = doc["subtitle_style"].get("size", 40) * 2 / 3
                project_path.write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
        config.update(quality=options["quality"], coverFrame=options["cover_frame"])
        config_path.write_text(json.dumps(config), "utf-8")
        if format == "mp4": return export_video(workspace, node, sink, source_id)
        if format == "png":
            run_process([node, str(ENGINE / "runner.mjs"), "cover", str(workspace)], workspace, sink, timeout=300)
            file = workspace / "out/cover.png"; kind = "animation-cover"; mime = "image/png"
        else:
            start = 0; frames = config["durationInFrames"]
            if options.get("scene_id"):
                selected = next((s for s in doc.get("scenes", []) if s["id"] == options["scene_id"]), None)
                if not selected: raise RuntimeError("所选分镜不存在。")
                for s in doc["scenes"]:
                    if s is selected: break
                    start += s["frames"]
                frames = selected["frames"]
            run_process([node, str(ENGINE / "runner.mjs"), "render", str(workspace)], workspace, sink, timeout=1200)
            file = workspace / "out/animation.gif"; kind = "animation-gif"; mime = "image/gif"
            filters = "fps=15,scale='if(gte(iw,ih),720,-2)':'if(gte(iw,ih),-2,720)':flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"
            run_process(["ffmpeg", "-y", "-v", "error", "-ss", str(start/30), "-t", str(min(frames/30, 15)), "-i", str(workspace / "out/animation.mp4"), "-an", "-filter_complex", filters, str(file)], workspace, sink, timeout=300)
        check_cancel(sink)
        sink.create_artifact(kind=kind, filename=file.name, content=file.read_bytes(), mime_type=mime, metadata={"source_run_id": str(source_id), **options})
    return {"source_run_id": str(source_id), "export_ready": True, "format": format}

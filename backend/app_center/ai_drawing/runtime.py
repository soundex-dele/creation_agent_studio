"""Codex image generation executed by the durable media worker."""
import logging
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import mkdtemp

from django.conf import settings
from django.http import Http404
from rest_framework.exceptions import APIException

from core.agent_engine.adapters.codex import CodexAdapter
from modules.execution.infrastructure.artifacts import get_artifact_storage, open_artifact
from modules.execution.models import Run
from modules.tenancy.database import tenant_database_context
from .backend.access import application_for, reference_for, source_for
from .backend.images import MAX_IMAGE_BYTES, inspect_image
from .backend.serializers import GenerateSerializer

logger = logging.getLogger(__name__)
ORIENTATIONS = {"auto": "按内容自动选择", "square": "方形", "landscape": "横向", "portrait": "纵向"}


def _cleanup_workspace(workspace, root):
    """Cleanup is best effort: a lingering Windows cwd handle is not a Run error."""
    for delay in (0, 0.1, 0.3):
        if delay:
            time.sleep(delay)
        try:
            # Only delete the exact temporary child we created. Never follow a
            # replacement symlink/junction or clean a parent/shared workspace.
            if workspace.is_symlink() or workspace.resolve() != workspace or workspace.parent != root:
                logger.warning("Skipping drawing workspace cleanup outside its original root: %s", workspace)
                return
            shutil.rmtree(workspace)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            error = exc
    logger.warning("Drawing workspace retained after cleanup failed: %s (%s)", workspace, error)


@contextmanager
def _attempt_workspace(root):
    root = Path(root).resolve()
    workspace = Path(mkdtemp(prefix="attempt-", dir=root))
    try:
        yield str(workspace)
    finally:
        # No tempfile finalizer: locked directories are deliberately retained,
        # and cleanup must never replace success, cancellation or a real error.
        _cleanup_workspace(workspace, root)


def _read_output(path_value, workspace):
    if not path_value:
        raise RuntimeError("Codex 未返回图片保存路径，请检查执行主机的 Codex 版本与生图能力。")
    path = Path(path_value).expanduser()
    roots = [Path(workspace).resolve(),
             (Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "generated_images").resolve()]
    if not path.is_absolute():
        raise RuntimeError("Codex 返回了无效的图片路径。")
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in roots):
        raise RuntimeError("Codex 图片路径不在本次任务或生成图片目录内。")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        raise RuntimeError("生成的图片文件已丢失或无法读取，请重新生成。") from None
    return content, inspect_image(content)


def execute(payload, sink):
    if str(settings.CODEX_TRANSPORT).lower() != "app-server":
        raise RuntimeError("AI 绘图需要 CODEX_TRANSPORT=app-server。")
    # Spawned workers do not inherit request tenant context. Keep the RLS
    # transaction short; network generation runs after all inputs are loaded.
    with tenant_database_context(payload["organization_id"]):
        run = Run.objects.for_organization(payload["organization_id"]).select_related("owner").get(pk=payload["run_id"])
        try:
            application = application_for(run.owner, run.organization_id, run.source_id)
            serializer = GenerateSerializer(data=payload["input"])
            serializer.is_valid(raise_exception=True)
            values = serializer.validated_data
            reference = reference_for(run.owner, application, values["reference_id"]) if values.get("reference_id") else None
            source = source_for(run.owner, application, values["source_artifact_id"]) if values.get("source_artifact_id") else None
        except (Http404, APIException):
            raise RuntimeError("绘图应用或参考图片不可用，请检查权限并重新选择图片。") from None
    if sink.cancelled:
        return {}
    root = Path(settings.AGENT_WORKSPACE_ROOT) / "ai-drawing" / str(run.organization_id) / str(run.id)
    root.mkdir(parents=True, exist_ok=True)
    outputs = []
    seen = set()
    with _attempt_workspace(root) as workspace:
        image_paths = []
        if reference or source:
            try:
                handle = get_artifact_storage().open(reference.object_key) if reference else open_artifact(source)
                try:
                    content = handle.read(MAX_IMAGE_BYTES + 1)
                finally:
                    handle.close()
                metadata = inspect_image(content)
                extension = metadata["mime_type"].split("/")[1]
                image_path = Path(workspace) / f"reference.{extension}"
                image_path.write_bytes(content)
                image_paths = [str(image_path)]
            except Exception:
                logger.exception("Drawing reference unavailable for run %s", run.id)
                raise RuntimeError("参考图文件不可用，请重新上传或选择作品。") from None

        def event(event_type, data):
            # Only publish our own safe progress payloads. Other Codex tool
            # events and agent text may contain local paths or inline binaries.
            if data.get("tool_type") != "imageGeneration":
                return
            if event_type == "tool.started":
                sink.emit("progress.updated", {"stage": "generating"})
            if event_type != "tool.completed" or data.get("tool_call_id") in seen:
                return
            if data.get("status") not in ("completed", "succeeded"):
                return
            seen.add(data["tool_call_id"])
            content, metadata = _read_output(data.get("saved_path"), workspace)
            if outputs:  # v1 requests a single candidate.
                return
            sink.emit("progress.updated", {"stage": "saving"})
            metadata["revised_prompt"] = str(data.get("revised_prompt") or "")[:16000]
            filename = "drawing." + metadata["mime_type"].split("/")[1]
            sink.create_artifact(kind="drawing", filename=filename, content=content,
                                 mime_type=metadata["mime_type"], metadata=metadata)
            outputs.append({"filename": filename, "width": metadata["width"], "height": metadata["height"]})

        sink.emit("progress.updated", {"stage": "generating"})
        instructions = (
            "你是 AI 绘图应用。必须调用内置 image_gen 图像生成工具，只生成一张图片。"
            "如有参考图片，将它作为编辑目标，按用户文字要求修改，其余主体细节尽量保持。"
            "不要用代码、SVG、HTML、绘图库、外部 API 或 CLI 替代内置生图工具。"
            "无需澄清，直接生成；工具不可用时明确报告失败。不要执行其他任务。"
        )
        try:
            result = CodexAdapter(model=(payload.get("effective_config") or {}).get("model")).complete(
                [{"role": "system", "content": instructions},
                 {"role": "user", "content": f"画面方向偏好：{ORIENTATIONS[values['orientation']]}\n绘图要求：{values['prompt']}"}],
                working_directory=workspace, image_paths=image_paths, on_event=event,
                cancelled=lambda: sink.cancelled,
                timeout_seconds=int((payload.get("effective_config") or {}).get("timeout_seconds", 600)),
                thread_config={"features.image_generation": True},
            )
        except TimeoutError:
            raise
        except Exception as exc:
            logger.exception("Codex drawing failed for run %s", run.id)
            # Do not return raw transport exceptions, which can contain local paths.
            if isinstance(exc, RuntimeError) and str(exc).startswith(("Codex 未返回", "Codex 返回", "Codex 图片", "生成的图片")):
                raise
            raise RuntimeError("Codex 生图执行失败，请检查执行主机的登录状态、网络和图像生成权限后重试。") from None
        if sink.cancelled:
            return {"images": outputs}
        if not result.success:
            raise RuntimeError("Codex 未完成生图，请检查登录状态、图像生成权限或稍后重试。")
        if not outputs:
            raise RuntimeError("Codex 未返回可用图片。当前会话可能未提供内置生图工具，请在执行主机检查 Codex 登录方式、所用模型和账号生图能力后重试；文字回复不算生成成功。")
    return {"images": outputs}

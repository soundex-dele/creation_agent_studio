"""Durable executor for rendering HTML files to PNG with Playwright."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from decouple import config as environment_config

from apps.workflows.artifacts import workspace_file
from .workflow_files import insert_illustrations, load_manifest


PRESETS = {
    "vertical": (1080, 1440),
    "horizontal": (1283, 383),
}
WAIT_UNTIL_VALUES = {"networkidle", "load", "domcontentloaded"}


def _is_within_allowed_roots(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _directories(config, allowed_roots, *, allow_all_paths=False):
    raw_directories = config.get("directories")
    if not isinstance(raw_directories, list) or not raw_directories:
        raise ValueError("请至少选择一个 HTML 目录。")
    if len(raw_directories) > 100:
        raise ValueError("一次最多处理 100 个目录。")

    directories = []
    seen = set()
    for raw in raw_directories:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("目录路径不能为空。")
        directory = Path(raw.strip()).expanduser().resolve(strict=False)
        if (
            not allow_all_paths
            and not _is_within_allowed_roots(directory, allowed_roots)
        ):
            raise PermissionError(f"目录不在允许的运行范围内：{directory}")
        if not directory.is_dir():
            raise ValueError(f"目录不存在或不可访问：{directory}")
        key = os.path.normcase(str(directory))
        if key not in seen:
            seen.add(key)
            directories.append(directory)
    return directories


def _html_files(directories):
    return [
        item.resolve(strict=False)
        for directory in directories
        for item in sorted(directory.iterdir(), key=lambda value: value.name.casefold())
        if item.is_file() and item.suffix.lower() == ".html"
    ]


def _number(config, key, default, *, minimum, maximum):
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} 必须是数字。")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} 必须在 {minimum} 到 {maximum} 之间。")
    return value


def _playwright_module_path(config):
    candidates = []
    configured = config.get("playwright_node_modules") or environment_config(
        "PLAYWRIGHT_NODE_MODULES", default=""
    )
    if configured:
        candidates.append(Path(configured).expanduser())
    reference_script = config.get("reference_script")
    if reference_script:
        candidates.append(Path(reference_script).expanduser().parent.parent / "node_modules")
    # Package-local dependencies work on every host without a developer's path.
    # Also accept an installation in a parent backend/repository directory.
    candidates.extend(parent / "node_modules" for parent in Path(__file__).resolve().parents)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if (resolved / "playwright").is_dir():
            return resolved
    return None


def _capture_config(config, files):
    orientation = str(config.get("orientation") or "horizontal")
    if orientation not in PRESETS:
        raise ValueError("orientation 只能是 horizontal 或 vertical。")
    preset_width, preset_height = PRESETS[orientation]
    width = int(_number(config, "width", preset_width, minimum=1, maximum=10000))
    height = int(_number(config, "height", preset_height, minimum=1, maximum=10000))
    scale = _number(config, "device_scale_factor", 2, minimum=1, maximum=4)
    wait_until = str(config.get("wait_until") or "networkidle")
    if wait_until not in WAIT_UNTIL_VALUES:
        raise ValueError("wait_until 参数无效。")
    selector = config.get("selector", ".cover")
    if selector is not None and not isinstance(selector, str):
        raise ValueError("selector 必须是字符串。")
    return {
        "files": [
            {"input": str(path), "output": str(path.with_suffix(".png"))}
            for path in files
        ],
        "width": width,
        "height": height,
        "deviceScaleFactor": scale,
        "waitUntil": wait_until,
        "navigationTimeout": 30000,
        "selector": selector.strip() if selector else "",
        "fullPage": bool(config.get("full_page", False)),
        "transparent": bool(config.get("transparent", False)),
        "noWebFonts": bool(config.get("no_web_fonts", False)),
    }


def execute_html_to_png(run_payload, sink):
    config = {
        **dict(run_payload.get("effective_config") or {}),
        **dict(run_payload.get("input") or {}),
    }
    allowed_roots = [
        Path(root).expanduser().resolve(strict=False)
        for root in run_payload.get("allowed_roots", [])
    ]
    allow_all_paths = bool(run_payload.get("allow_all_paths", False))
    if not allow_all_paths and not allowed_roots:
        raise PermissionError("未配置应用可访问的目录范围。")
    manifest_path = None
    manifest = None
    if config.get("manifest_file"):
        manifest_path, manifest, files = load_manifest(config)
    elif config.get("html_file"):
        file = workspace_file(config.get("working_directory"), config["html_file"])
        if not file.is_file() or file.suffix.lower() != ".html":
            raise ValueError("指定的 HTML 文件不存在或类型无效。")
        files = [file]
    else:
        directories = _directories(config, allowed_roots, allow_all_paths=allow_all_paths)
        files = _html_files(directories)
    for file in files:
        if not allow_all_paths and any(
            not _is_within_allowed_roots(path.resolve(), allowed_roots)
            for path in (file, file.with_suffix(".png"))
        ):
            raise PermissionError("HTML 或 PNG 路径不在允许的运行范围内。")
        if config.get("working_directory"):
            workspace_file(config["working_directory"], str(file.with_suffix(".png")))
    if config.get("article_source") and manifest is None:
        raise ValueError("正文插图需要提供配图清单。")
    if not files:
        if config.get("strict"):
            raise ValueError("没有可导出的 HTML 文件。")
        return {
            "status": "completed",
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "files": [],
            "message": "所选目录中没有 HTML 文件。",
        }

    node = shutil.which("node")
    if not node:
        raise RuntimeError("HTML 转 PNG 功能不可用：未安装 Node.js。")
    module_path = _playwright_module_path(config)
    if module_path is None:
        raise RuntimeError(
            "HTML 转 PNG 功能不可用：未找到 Playwright。"
            "请在 backend/app_center/html_to_png 中运行 npm ci 和 "
            "npx playwright install chromium，或设置 PLAYWRIGHT_NODE_MODULES。"
        )

    capture_config = _capture_config(config, files)
    helper = Path(__file__).with_name("capture.js")
    env = os.environ.copy()
    # Node's local module lookup takes precedence over NODE_PATH. Pass the
    # selected directory explicitly so shared installations are actually used.
    env["PLAYWRIGHT_NODE_MODULES"] = str(module_path)
    current_node_path = env.get("NODE_PATH", "")
    env["NODE_PATH"] = os.pathsep.join(
        value for value in (str(module_path), current_node_path) if value
    )
    process = subprocess.Popen(
        [node, str(helper)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(capture_config, ensure_ascii=False))
    process.stdin.close()

    outputs = []
    failures = []
    total = len(files)
    for line in process.stdout:
        if sink.cancelled:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            return {"status": "cancelled", "files": outputs, "failures": failures}
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        index = int(event.get("index") or 0)
        if event_type == "started":
            sink.emit("tool.started", {
                "tool_call_id": str(index),
                "name": "html-to-png",
                "file": event.get("input"),
            })
        elif event_type == "completed":
            output = str(event.get("output") or "")
            if not 1 <= index <= total or output != str(files[index - 1].with_suffix(".png")):
                process.terminate()
                process.wait(timeout=5)
                raise RuntimeError("截图进程返回了非预期的输出路径。")
            sink.create_artifact(
                kind="result",
                filename=Path(output).name,
                content=Path(output).read_bytes(),
                mime_type="image/png",
            )
            outputs.append(output)
            sink.emit("output.delta", {"text": f"✓ {output}\n"})
            sink.emit("tool.completed", {
                "tool_call_id": str(index),
                "name": "html-to-png",
                "file": event.get("input"),
                "output": output,
            })
            sink.emit("progress.updated", {"current": index, "total": total})
        elif event_type == "failed":
            failure = {
                "file": str(event.get("input") or ""),
                "error": str(event.get("error") or "截图失败"),
            }
            failures.append(failure)
            sink.emit("output.delta", {
                "text": f"✗ {failure['file']}：{failure['error']}\n"
            })
            sink.emit("tool.completed", {
                "tool_call_id": str(index),
                "name": "html-to-png",
                **failure,
                "status": "failed",
            })
            sink.emit("progress.updated", {"current": index, "total": total})

    stderr = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait()
    if return_code != 0:
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "未知错误"
        raise RuntimeError(f"Playwright 截图进程失败：{detail}")
    if config.get("strict") or config.get("article_source"):
        expected = [str(file.with_suffix(".png")) for file in files]
        if failures or outputs != expected:
            raise RuntimeError("HTML 导出未全部成功，停止下游处理。")
        for output in outputs:
            with Path(output).open("rb") as png:
                if png.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError("导出产物不是有效的 PNG 文件。")
    result = {
        "status": "completed",
        "total": total,
        "succeeded": len(outputs),
        "failed": len(failures),
        "files": outputs,
        "failures": failures,
    }
    if config.get("article_source"):
        result["article_md"] = insert_illustrations(config, manifest_path, manifest, files, outputs)
        article = Path(result["article_md"])
        sink.create_artifact(
            kind="result", filename=article.name,
            content=article.read_bytes(), mime_type="text/markdown",
        )
    return result

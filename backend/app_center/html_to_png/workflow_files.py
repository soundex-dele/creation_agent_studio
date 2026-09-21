"""Manifest-based rendering and deterministic insertion of exported illustrations."""
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from apps.workflows.artifacts import workspace_file


def load_manifest(config):
    path = workspace_file(config.get("working_directory"), config.get("manifest_file"))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("HTML 清单必须包含 files 数组。")
    files = manifest["files"]
    if not files or len(files) > 200 or any(not isinstance(item, str) or not item for item in files):
        raise ValueError("HTML 清单必须包含 1 至 200 个有效文件路径。")
    resolved = [workspace_file(config["working_directory"], str(path.parent / item)) for item in files]
    if len(set(resolved)) != len(resolved):
        raise ValueError("HTML 清单包含重复文件。")
    for file in resolved:
        if file.suffix.lower() != ".html" or not file.is_file():
            raise ValueError(f"清单中的 HTML 文件不存在或类型无效：{file.name}")
    return path, manifest, resolved


def insert_illustrations(config, manifest_path, manifest, html_files, png_files):
    """Only insert images at unique complete Markdown blocks; preserve all original copy."""
    source = workspace_file(config.get("working_directory"), config.get("article_source"))
    # Keep existing relative links/images valid by writing beside the original Markdown.
    output = workspace_file(config["working_directory"], str(source.with_name("article-with-images.md")))
    if output == source:
        raise ValueError("插图正文不能覆盖原稿。")
    insertions = manifest.get("insertions")
    if not isinstance(insertions, list) or len(insertions) != len(html_files):
        raise ValueError("每张配图必须在 insertions 中指定一个正文插入位置。")
    blocks = re.split(r"(\n[ \t]*\n)", source.read_text(encoding="utf-8"))
    rendered = {str(html): png for html, png in zip(html_files, png_files)}
    additions = {}
    used = set()
    for entry in insertions:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ValueError("配图插入记录必须提供 file。")
        html = workspace_file(config["working_directory"], str(manifest_path.parent / entry["file"]))
        if str(html) not in rendered or str(html) in used:
            raise ValueError("配图插入记录与 HTML 清单不一致或重复。")
        anchor = entry.get("after")
        if not isinstance(anchor, str) or not anchor.strip():
            raise ValueError("配图必须提供原文完整段落作为 after 锚点。")
        matches = [index for index in range(0, len(blocks), 2) if blocks[index].strip() == anchor.strip()]
        if len(matches) != 1:
            raise ValueError("配图锚点不存在或不唯一，请提供原文完整且唯一的段落。")
        png = Path(rendered[str(html)])
        alt = str(entry.get("alt") or "文章配图").replace("\n", " ").replace("[", "\\[").replace("]", "\\]")
        relative = quote(Path(os.path.relpath(png, output.parent)).as_posix(), safe="/")
        additions.setdefault(matches[0], []).append(f"![{alt}]({relative})")
        used.add(str(html))
    for index, images in additions.items():
        blocks[index] += "\n\n" + "\n\n".join(images)
    output.write_text("".join(blocks), encoding="utf-8")
    return str(output)

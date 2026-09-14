"""Discover the latest filesystem Skills for the selected Agent adapter."""
import re
from pathlib import Path

from django.conf import settings


_ADAPTER_DIRECTORY_SETTINGS = {
    "codex": "CODEX_SKILLS_DIRECTORY",
    "graphflow": "GRAPHFLOW_SKILLS_DIRECTORY",
}


def resolve_skill_adapter(adapter_name: str = "") -> str:
    adapter = str(adapter_name or settings.AGENT_ENGINE_ADAPTER).strip().lower()
    if adapter not in _ADAPTER_DIRECTORY_SETTINGS:
        raise ValueError(f"适配器 {adapter or '<empty>'} 没有配置 Skill 目录。")
    return adapter


def skill_directory_for_adapter(adapter_name: str = "") -> Path:
    adapter = resolve_skill_adapter(adapter_name)
    setting_name = _ADAPTER_DIRECTORY_SETTINGS[adapter]
    return Path(getattr(settings, setting_name)).expanduser().resolve(strict=False)


def _frontmatter_value(content: str, key: str) -> str:
    match = re.search(
        rf'^\s*{re.escape(key)}:\s*["\']?(.+?)["\']?\s*$',
        content,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def discover_runtime_skills(adapter_name: str = "") -> list[dict]:
    """Read current SKILL.md metadata directly from the adapter directory."""

    adapter = resolve_skill_adapter(adapter_name)
    root = skill_directory_for_adapter(adapter)
    if not root.is_dir():
        return []
    discovered = {}
    # Direct user Skills take precedence over nested/bundled Skills with the
    # same name. Remaining nested roots (for example Codex .system) follow.
    skill_files = [*root.glob("*/SKILL.md"), *root.rglob("SKILL.md")]
    for skill_file in skill_files:
        resolved = skill_file.resolve()
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        name = _frontmatter_value(content, "name") or resolved.parent.name
        if not name or name in discovered:
            continue
        discovered[name] = {
            "name": name,
            "display_name": name,
            "description": _frontmatter_value(content, "description"),
            "path": str(resolved),
            "adapter": adapter,
        }
    return sorted(discovered.values(), key=lambda item: item["name"].casefold())


def resolve_runtime_skills(skill_names, adapter_name: str = "") -> list[dict]:
    """Resolve selected names against a fresh adapter-directory scan."""

    requested = []
    seen = set()
    for value in skill_names or []:
        name = str(value or "").strip()
        if name and name not in seen:
            seen.add(name)
            requested.append(name)
    available = {
        skill["name"]: skill
        for skill in discover_runtime_skills(adapter_name)
    }
    missing = [name for name in requested if name not in available]
    if missing:
        adapter = resolve_skill_adapter(adapter_name)
        root = skill_directory_for_adapter(adapter)
        raise ValueError(
            f"{adapter} Skill 目录 {root} 中不存在：{', '.join(missing)}"
        )
    return [available[name] for name in requested]

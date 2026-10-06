"""Filesystem access policy shared by server-side applications."""
import os
import string
from pathlib import Path

from django.conf import settings

from core.resource_access import is_platform_admin
from core.user_directories import user_directory


def allow_all_runtime_paths(user) -> bool:
    return bool(is_platform_admin(user) and user.is_active
                and getattr(settings, "APPLICATION_RUNTIME_ALLOW_ALL_PATHS", True))


def configured_runtime_roots() -> list[Path]:
    return [Path(root).expanduser().resolve(strict=False)
            for root in settings.APPLICATION_RUNTIME_ALLOWED_ROOTS]


def filesystem_roots() -> list[Path]:
    if os.name == "nt":
        return [root for letter in string.ascii_uppercase
                if (root := Path(f"{letter}:/")).is_dir()]
    return [Path("/")]


def runtime_roots(user) -> list[Path]:
    own_root = user_directory(user)
    if allow_all_runtime_paths(user):
        return filesystem_roots()
    if is_platform_admin(user):
        return [own_root, *configured_runtime_roots()]
    return [own_root]


def visible_runtime_roots(user) -> list[Path]:
    return [root for root in runtime_roots(user) if root.is_dir()]


def resolve_runtime_path(raw_path: str, user) -> Path:
    roots = runtime_roots(user)
    try:
        if not raw_path or '\x00' in raw_path:
            raise ValueError('Invalid path')
        target = Path(raw_path).expanduser().resolve(strict=False)
    except (ValueError, OSError, RuntimeError) as exc:
        raise PermissionError('无效或不可访问的路径。') from exc
    if not any(target == root or root in target.parents for root in roots):
        raise PermissionError("无权限访问该路径，只能访问自己的用户目录。")
    return target


def runtime_path_is_accessible(path, user) -> bool:
    try:
        resolve_runtime_path(str(path), user)
        return True
    except (PermissionError, OSError, ValueError, RuntimeError):
        return False


def runtime_parent(path, user) -> str:
    parent = path.parent
    return str(parent) if parent != path and runtime_path_is_accessible(parent, user) else ""

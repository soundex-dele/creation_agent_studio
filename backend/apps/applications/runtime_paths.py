"""Filesystem access policy shared by server-side applications."""

import os
import string
from pathlib import Path

from django.conf import settings


def allow_all_runtime_paths() -> bool:
    return bool(getattr(settings, "APPLICATION_RUNTIME_ALLOW_ALL_PATHS", True))


def configured_runtime_roots() -> list[Path]:
    return [
        Path(root).expanduser().resolve(strict=False)
        for root in settings.APPLICATION_RUNTIME_ALLOWED_ROOTS
    ]


def filesystem_roots() -> list[Path]:
    if os.name == "nt":
        return [
            root
            for letter in string.ascii_uppercase
            if (root := Path(f"{letter}:/")).is_dir()
        ]
    return [Path("/")]


def visible_runtime_roots() -> list[Path]:
    if allow_all_runtime_paths():
        return filesystem_roots()
    return [root for root in configured_runtime_roots() if root.is_dir()]


def resolve_runtime_path(raw_path: str) -> Path:
    target = Path(raw_path).expanduser().resolve(strict=False)
    if allow_all_runtime_paths():
        return target
    roots = configured_runtime_roots()
    if not roots:
        raise PermissionError("Server-side file browsing is disabled.")
    if not any(target == root or root in target.parents for root in roots):
        raise PermissionError("Path is outside the configured runtime roots.")
    return target

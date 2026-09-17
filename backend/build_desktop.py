#!/usr/bin/env python
"""Build Agent Studio for Windows, excluding Creation Master."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
SPEC_FILE = BACKEND_ROOT / "agent_studio.spec"
BUILD_DIR = BACKEND_ROOT / "build" / "agent_studio"
DIST_DIR = BACKEND_ROOT / "dist"


def run(command: list[str], *, cwd: Path, env=None) -> None:
    print("  >", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def build() -> None:
    license_enabled = os.environ.get(
        "LICENSE_AUTH_ENABLED", "False"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if license_enabled and not os.environ.get("LICENSE_PUBLIC_KEY", "").strip():
        raise SystemExit(
            "LICENSE_AUTH_ENABLED is true, but LICENSE_PUBLIC_KEY is empty."
        )

    print("[1/4] Building React frontend without Creation Master")
    frontend_env = os.environ.copy()
    frontend_env["VITE_EXCLUDE_CREATION_MASTER"] = "true"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    run([npm, "run", "build"], cwd=FRONTEND_ROOT, env=frontend_env)

    print("[2/4] Collecting Django static assets")
    django_env = os.environ.copy()
    django_env.update({
        "DJANGO_SETTINGS_MODULE": "backend.settings.desktop",
        "DATABASE_ENGINE": "sqlite",
        "REDIS_ENABLED": "False",
        "SECRET_KEY": "desktop-static-collection-only-secret-key",
    })
    run([
        sys.executable,
        "manage.py",
        "collectstatic",
        "--noinput",
        "--clear",
    ], cwd=BACKEND_ROOT, env=django_env)

    print("[3/4] Checking PyInstaller")
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is not installed. Run: "
            f'"{sys.executable}" -m pip install -r requirements/desktop.txt'
        ) from exc

    print("[4/4] Building Windows distribution")
    build_env = os.environ.copy()
    build_env.update({
        "DJANGO_SETTINGS_MODULE": "backend.settings.desktop",
        "DATABASE_ENGINE": "sqlite",
        "REDIS_ENABLED": "False",
        "SECRET_KEY": "pyinstaller-analysis-only-secret-key",
    })
    run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(BUILD_DIR),
        "--distpath",
        str(DIST_DIR),
        str(SPEC_FILE),
    ], cwd=BACKEND_ROOT, env=build_env)
    output = DIST_DIR / "AgentStudio" / "AgentStudio.exe"
    print(f"Build complete: {output}")


def clean() -> None:
    targets = [BUILD_DIR, DIST_DIR / "AgentStudio"]
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
            print(f"Removed {target}")


if __name__ == "__main__":
    if sys.argv[1:] == ["clean"]:
        clean()
    elif sys.argv[1:]:
        raise SystemExit("Usage: python build_desktop.py [clean]")
    else:
        build()

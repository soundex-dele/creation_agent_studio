# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for Agent Studio (without Creation Master)."""

import os
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


BACKEND_ROOT = Path(SPECPATH)
PROJECT_ROOT = BACKEND_ROOT.parent

# License mode is a distributor-controlled build setting. Embed it in a
# runtime hook instead of placing an editable switch next to the executable.
license_enabled = os.environ.get("LICENSE_AUTH_ENABLED", "False").strip().lower() in {
    "1", "true", "yes", "on",
}
license_public_key = os.environ.get("LICENSE_PUBLIC_KEY", "").strip()
if license_enabled and not license_public_key:
    raise ValueError("LICENSE_AUTH_ENABLED is true, but LICENSE_PUBLIC_KEY is empty")
runtime_hook = BACKEND_ROOT / "build" / "agent_studio" / "license_runtime_hook.py"
runtime_hook.parent.mkdir(parents=True, exist_ok=True)
runtime_values = {
    "LICENSE_AUTH_ENABLED": "True" if license_enabled else "False",
    "LICENSE_PRODUCT_ID": os.environ.get("LICENSE_PRODUCT_ID", "agent-studio").strip(),
    "LICENSE_PUBLIC_KEY": license_public_key,
}
runtime_hook.write_text(
    "import os\n" + "".join(
        f"os.environ[{key!r}] = {value!r}\n"
        for key, value in runtime_values.items()
    ),
    encoding="utf-8",
)


def tree_data(source: Path, destination: str, *, excluded_parts=()):
    result = []
    if not source.exists():
        return result
    for path in source.rglob("*"):
        if not path.is_file() or any(part in excluded_parts for part in path.parts):
            continue
        relative_parent = path.relative_to(source).parent
        result.append((str(path), str(Path(destination) / relative_parent)))
    return result


datas = tree_data(PROJECT_ROOT / "frontend" / "dist", "frontend_dist")
datas += tree_data(
    BACKEND_ROOT / "app_center",
    "app_center",
    excluded_parts={"creation_master", "__pycache__"},
)
datas += tree_data(BACKEND_ROOT / "static", "static", excluded_parts={"__pycache__"})
datas += tree_data(BACKEND_ROOT / "staticfiles", "staticfiles", excluded_parts={"__pycache__"})
datas += collect_data_files("django", include_py_files=False)
datas += collect_data_files("rest_framework", include_py_files=False)
datas += collect_data_files("drf_yasg", include_py_files=False)
datas += collect_data_files("allauth", include_py_files=False)
datas += collect_data_files("autobahn", include_py_files=False)
datas += collect_data_files("sqlite_vec", include_py_files=False)

binaries = []
ffmpeg_dir = os.environ.get("FFMPEG_DIR", "").strip()
if not ffmpeg_dir:
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_dir = str(Path(ffmpeg_path).parent) if ffmpeg_path else ""
if ffmpeg_dir:
    for executable in ("ffmpeg.exe", "ffprobe.exe"):
        candidate = Path(ffmpeg_dir) / executable
        if candidate.is_file():
            binaries.append((str(candidate), "ffmpeg"))

def runtime_module(name):
    parts = name.split(".")
    return "tests" not in parts and not any(part.startswith("test_") for part in parts)


hiddenimports = []
for package in ("backend", "apps", "core", "modules"):
    hiddenimports += collect_submodules(package, filter=runtime_module)
for package in ("app_center.batch_transcribe", "app_center.contacts"):
    hiddenimports += collect_submodules(package, filter=runtime_module)
hiddenimports += collect_submodules("whitenoise", filter=runtime_module)
hiddenimports += ["pystray._win32"]

a = Analysis(
    [str(BACKEND_ROOT / "desktop_launcher.py")],
    pathex=[str(BACKEND_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(runtime_hook)],
    excludes=[
        "app_center.creation_master",
        "debug_toolbar",
        "PySide6",
        "PyQt5",
        "PyQt6",
        "tkinter",
    ],
    noarchive=False,
)

# PyInstaller's Django hook scans the project root and may pick up the live
# development SQLite sidecar files while its analysis process still holds
# them open.  Desktop state is created under LOCALAPPDATA at first launch, so
# no source-tree database belongs in the distribution.
a.datas = [
    entry for entry in a.datas
    if not Path(entry[0]).name.startswith("db.sqlite3")
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="AgentStudio",
)

"""Windows launcher for the packaged Creation Agent Studio application."""

from __future__ import annotations

import multiprocessing
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path


APP_NAME = "CreationAgentStudio"
HOST = "127.0.0.1"
PORT = 8765
LOG_PATH: Path | None = None
LOG_STREAM = None


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _data_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / APP_NAME


def _secret_key(data_root: Path) -> str:
    path = data_root / ".secret-key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(64)
    path.write_text(value, encoding="utf-8")
    return value


def _configure_stdio(data_root: Path) -> None:
    """Give windowed PyInstaller processes a real stream for Django output."""
    global LOG_PATH, LOG_STREAM
    LOG_PATH = data_root / "logs" / f"creation-agent-studio-{os.getpid()}.log"
    if sys.stdout is None or sys.stderr is None:
        LOG_STREAM = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = LOG_STREAM
        if sys.stderr is None:
            sys.stderr = LOG_STREAM


def configure_environment() -> tuple[Path, Path]:
    bundle_root = _bundle_root()
    data_root = _data_root()
    for name in ("media", "artifacts", "agent-workspaces", "logs"):
        (data_root / name).mkdir(parents=True, exist_ok=True)
    _configure_stdio(data_root)

    values = {
        "DJANGO_SETTINGS_MODULE": "backend.settings.desktop",
        "DATABASE_ENGINE": "sqlite",
        "REDIS_ENABLED": "False",
        "SQLITE_PATH": str(data_root / "creation-agent-studio.sqlite3"),
        "MEDIA_ROOT": str(data_root / "media"),
        "ARTIFACT_ROOT": str(data_root / "artifacts"),
        "AGENT_WORKSPACE_ROOT": str(data_root / "agent-workspaces"),
        "APPLICATION_RUNTIME_ALLOWED_ROOTS": str(data_root),
        "APP_CENTER_ROOT": str(bundle_root / "app_center"),
        "CREATION_STUDIO_FRONTEND_DIST": str(bundle_root / "frontend_dist"),
        "SECRET_KEY": _secret_key(data_root),
        "ALLOWED_HOSTS": "127.0.0.1,localhost",
    }
    for key, value in values.items():
        os.environ[key] = value

    ffmpeg_dir = bundle_root / "ffmpeg"
    if ffmpeg_dir.is_dir():
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
    return bundle_root, data_root


def _run_management_command(name: str, *args: str) -> None:
    import django
    from django.core.management import call_command

    django.setup()
    call_command(name, *args, verbosity=1)


def _run_server() -> None:
    from daphne.cli import CommandLineInterface

    CommandLineInterface().run([
        "-b", HOST,
        "-p", str(PORT),
        "backend.desktop_asgi:application",
    ])


def _run_coordinator() -> None:
    _run_management_command("run_execution_coordinator", "--worker-pool", "all")


def _run_scheduler() -> None:
    _run_management_command("run_automation_scheduler")


def _internal_mode(mode: str) -> None:
    if mode == "server":
        _run_server()
    elif mode == "coordinator":
        _run_coordinator()
    elif mode == "scheduler":
        _run_scheduler()
    else:
        raise SystemExit(f"Unknown internal mode: {mode}")


def _child_command(mode: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal", mode]
    return [sys.executable, str(Path(__file__).resolve()), "--internal", mode]


def _spawn(mode: str) -> subprocess.Popen:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(_child_command(mode), creationflags=creation_flags)


def _wait_until_ready(process: subprocess.Popen, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://{HOST}:{PORT}/healthz/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def _tray_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=15, fill="#5b4bea")
    draw.ellipse((15, 15, 31, 31), fill="white")
    draw.ellipse((34, 15, 50, 31), fill="#b9b2ff")
    draw.rounded_rectangle((15, 35, 50, 49), radius=7, fill="white")
    return image


def _run_tray(children: list[subprocess.Popen]) -> None:
    import pystray

    application_url = f"http://{HOST}:{PORT}/"

    def open_application(_icon=None, _item=None):
        webbrowser.open(application_url)

    def exit_application(icon, _item=None):
        icon.stop()

    icon = pystray.Icon(
        APP_NAME,
        _tray_image(),
        "Creation Agent Studio",
        menu=pystray.Menu(
            pystray.MenuItem("打开 Creation Agent Studio", open_application, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出应用", exit_application),
        ),
    )

    def stop_if_service_exits():
        children[0].wait()
        icon.stop()

    threading.Thread(target=stop_if_service_exits, daemon=True).start()
    open_application()
    icon.run()


def _stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()


def main() -> int:
    multiprocessing.freeze_support()
    configure_environment()

    if len(sys.argv) == 3 and sys.argv[1] == "--internal":
        _internal_mode(sys.argv[2])
        return 0

    _run_management_command("migrate", "--noinput")
    _run_management_command("sync_app_center")

    children = [_spawn("server"), _spawn("coordinator"), _spawn("scheduler")]
    try:
        if not _wait_until_ready(children[0]):
            raise RuntimeError("The local Creation Agent Studio server did not start")
        _run_tray(children)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        _stop_children(children)


def _show_startup_error(error: Exception) -> None:
    traceback.print_exc()
    if os.name != "nt" or "--internal" in sys.argv:
        return
    import ctypes

    log_hint = f"\n\n日志：{LOG_PATH}" if LOG_PATH else ""
    ctypes.windll.user32.MessageBoxW(
        None,
        f"Creation Agent Studio 启动失败：\n{error}{log_hint}",
        "Creation Agent Studio",
        0x10,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        _show_startup_error(exc)
        raise SystemExit(1)

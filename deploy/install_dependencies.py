"""Install repository dependencies using the project virtual environment only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PNG = ROOT / "backend/app_center/html_to_png"
ANIMATION = ROOT / "backend/app_center/animation_studio/engine"
DTK = ROOT / "backend/app_center/douyin_benchmark"
DTK_VENV = ROOT / "backend/.venv-dtk"
CATALOG = ROOT / "deploy/application_dependencies.json"
CODEX_VERSION = "0.155.0"  # Keep aligned with backend/Dockerfile.


def run(command, *, cwd=ROOT, dry_run=False, env=None):
    command = [str(part) for part in command]
    print(f"[{Path(cwd).relative_to(ROOT) if Path(cwd).is_relative_to(ROOT) else cwd}] "
          + subprocess.list2cmdline(command), flush=True)
    if not dry_run:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def require_program(name):
    program = shutil.which(name)
    if not program:
        raise RuntimeError(f"{name} is missing from PATH. Install it and open a new terminal first.")
    return program


def ensure_windows_venv_idle(venv=None):
    """Fail before pip can partially uninstall DLLs loaded by running services."""
    if sys.platform != "win32":
        return
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "@(Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine) | "
        "ConvertTo-Json -Compress"
    )
    output = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True, encoding="utf-8",
    )
    processes = json.loads(output or "[]")
    if isinstance(processes, dict):
        processes = [processes]
    # Windows venv Python uses a launcher plus a host-interpreter child.
    # Ignore this installer and its ancestors, but not other venv processes.
    parents = {process["ProcessId"]: process["ParentProcessId"] for process in processes}
    ancestors = {os.getpid()}
    parent = os.getppid()
    while parent and parent not in ancestors:
        ancestors.add(parent)
        parent = parents.get(parent)
    prefix = str(Path(venv or sys.prefix).resolve()).replace("\\", "/").casefold().rstrip("/") + "/"
    busy = []
    for process in processes:
        if process["ProcessId"] in ancestors:
            continue
        executable = (process.get("ExecutablePath") or "").replace("\\", "/").casefold()
        command = (process.get("CommandLine") or "").replace("\\", "/").casefold()
        if executable.startswith(prefix) or command.lstrip('"').startswith(prefix):
            busy.append(f"PID {process['ProcessId']}: {process.get('CommandLine') or process.get('ExecutablePath')}")
    if busy:
        raise RuntimeError(
            "The backend virtual environment is in use. Windows cannot replace loaded .pyd/DLL files "
            "(WinError 5). Stop these backend services/workers, then rerun the same installer:\n"
            + "\n".join(busy)
        )


def npm_command(node):
    npm = Path(require_program("npm.cmd" if os.name == "nt" else "npm"))
    if os.name != "nt":
        return [str(npm)]
    # Invoke npm's JS entry directly, avoiding cmd.exe quoting for paths with spaces.
    cli = npm.parent / "node_modules/npm/bin/npm-cli.js"
    if not cli.is_file():
        raise RuntimeError(f"Cannot locate npm CLI at {cli}. Repair the Node.js installation.")
    return [node, str(cli)]


def system_commands(platform):
    if platform == "win32":
        return [[require_program("winget"), "install", "--id", "Gyan.FFmpeg", "--exact",
                 "--silent", "--accept-package-agreements", "--accept-source-agreements"]]
    if platform == "darwin":
        return [[require_program("brew"), "install", "ffmpeg"]]
    if platform.startswith("linux"):
        apt = require_program("apt-get")
        prefix = [] if os.geteuid() == 0 else [require_program("sudo")]
        return [prefix + [apt, "update"], prefix + [apt, "install", "-y", "--no-install-recommends",
                "ffmpeg", "fonts-noto-cjk", "fonts-noto-color-emoji"]]
    raise RuntimeError("Unsupported OS for --system-deps; install FFmpeg manually.")


def application_selection(requested, catalog):
    selected = list(dict.fromkeys(name for value in requested for name in value.split(","))) if requested else list(catalog)
    unknown = set(selected) - catalog.keys()
    if unknown:
        raise RuntimeError("Unknown application(s): " + ", ".join(sorted(unknown)) + ". Use --list-apps to see supported IDs.")
    return selected


def install_png(execute, node, *, system_deps=False):
    browser_args = ["install", "chromium"]
    if system_deps and sys.platform.startswith("linux"):
        browser_args.append("--with-deps")
    # Install into Playwright's normal per-user cache. Run as the service account.
    execute([node, PNG / "node_modules/playwright/cli.js", *browser_args], cwd=PNG)
    smoke = (
        "const {chromium}=require('playwright'); "
        "(async()=>{const b=await chromium.launch({headless:true}); "
        "try {const p=await b.newPage(); await p.setContent('<h1>Ready</h1>'); "
        "await p.screenshot(); console.log('Chromium PNG check passed');} "
        "finally {await b.close();}})().catch(e=>{console.error(e);process.exit(1)});"
    )
    execute([node, "-e", smoke], cwd=PNG)


def install_animation(execute, node, npm):
    execute(npm + ["run", "browser"], cwd=ANIMATION)
    smoke = (
        "const {openBrowser}=require('@remotion/renderer'); "
        "(async()=>{const b=await openBrowser('chrome', "
        "{browserExecutable:process.env.ANIMATION_BROWSER_EXECUTABLE||undefined}); "
        "try {console.log('Remotion '+require('remotion/package.json').version+' browser check passed');} "
        "finally {await b.close({silent:true});}})().catch(e=>{console.error(e);process.exit(1)});"
    )
    execute([node, "-e", smoke], cwd=ANIMATION)


def install_dtk(execute):
    """Keep DTK's Python and packages separate from the Django environment."""
    execute([sys.executable, "-X", "utf8", DTK / "deploy/verify_source.py"])
    python = DTK_VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        if DTK_VENV.exists():
            raise RuntimeError(f"Incomplete DTK environment: {DTK_VENV}. Move it aside and rerun the installer.")
        if (3, 12) <= sys.version_info < (3, 14):
            execute([sys.executable, "-m", "venv", "--without-pip", DTK_VENV])
        else:
            # uv can provision Python 3.13 even when Django uses Python 3.11.
            execute([sys.executable, "-m", "pip", "install", "uv>=0.6,<1"])
            execute([sys.executable, "-m", "uv", "venv", "--python", "3.13", DTK_VENV])
    # Fail before pip changes an existing environment with an unsupported Python.
    execute([python, "-X", "utf8", "-c",
             "import sys; "
             "sys.exit(0 if (3, 12) <= sys.version_info < (3, 14) and sys.prefix != sys.base_prefix "
             "else 'DTK requires a separate Python 3.12/3.13 virtual environment; move backend/.venv-dtk aside and rerun.')"])
    # --python also supports uv/--without-pip environments without their own pip.
    pip = [sys.executable, "-m", "pip", "--python", python]
    execute(pip + ["install", "-r", ROOT / "backend/scripts/douyin_video_url.requirements.txt"])
    execute(pip + ["check"])
    execute([python, "-X", "utf8", DTK / "collector_source_checks.py"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", help="Include test/development Python packages")
    parser.add_argument("--system-deps", action="store_true", help="Install FFmpeg and Linux Chromium system libraries (may require admin/sudo)")
    parser.add_argument("--with-creation-master", action="store_true", help="Install optional Windows Creation Master desktop Python packages")
    parser.add_argument("--with-mobile", action="store_true", help="Install mobile npm packages (not Android/iOS SDKs)")
    parser.add_argument("--with-codex", action="store_true", help="Install the pinned Codex CLI globally")
    parser.add_argument("--skip-submodules", action="store_true", help="Use already initialized submodules or a source archive")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without changing files or installing packages")
    parser.add_argument("--app", action="append", default=[], help="Application ID (repeat or comma-separate); default: all. Shared backend/frontend dependencies are always included.")
    parser.add_argument("--list-apps", action="store_true", help="List applications, extra runtimes and external prerequisites without installing anything")
    args = parser.parse_args(argv)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["applications"]
    selected = application_selection(args.app, catalog)
    if args.list_apps:
        for name in selected:
            app = catalog[name]
            print(f"{name}: {app['name']} | shared backend/frontend" +
                  (" + " + ", ".join(app["runtimes"]) if app["runtimes"] else ""))
            for note in app.get("notes", []):
                print("  " + note)
            if app.get("skills"):
                print("  Skills: " + ", ".join(app["skills"]))
        return
    runtimes = {runtime for name in selected for runtime in catalog[name]["runtimes"]}
    if args.with_creation_master:
        runtimes.add("ffmpeg")
    # Playwright's supported distro installer also supplies Chrome Headless Shell's libraries.
    if "animation" in runtimes and args.system_deps and sys.platform.startswith("linux"):
        runtimes.add("png")
    print("Applications: " + ", ".join(selected), flush=True)

    allowed_venvs = {(ROOT / "backend/venv").resolve(), (ROOT / "backend/.venv").resolve()}
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() not in allowed_venvs:
        raise RuntimeError("Use install-dependencies.ps1/.sh or the backend project virtual environment.")
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required; Python 3.12 is recommended.")
    if args.with_creation_master and sys.platform != "win32":
        raise RuntimeError("Creation Master's desktop requirements include Windows automation; use this option on Windows only.")
    if not args.dry_run:
        ensure_windows_venv_idle()
        if "dtk" in runtimes:
            ensure_windows_venv_idle(DTK_VENV)
    node = require_program("node")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    major, minor = (int(value) for value in version.lstrip("v").split(".")[:2])
    if not ((major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major >= 24):
        raise RuntimeError(f"Node {version} is unsupported. Install Node.js 22.12+ LTS or 24 LTS.")
    npm = npm_command(node)
    git = require_program("git") if not args.skip_submodules else None
    execute = lambda command, **kwargs: run(command, dry_run=args.dry_run, **kwargs)
    ffmpeg_missing = "ffmpeg" in runtimes and (not shutil.which("ffmpeg") or not shutil.which("ffprobe"))
    if ffmpeg_missing and not args.system_deps:
        raise RuntimeError("FFmpeg/ffprobe is missing. Re-run with --system-deps (-SystemDeps on Windows), or install FFmpeg and add it to PATH.")
    if args.system_deps:
        # Install Linux fonts even when FFmpeg is already present.
        if ffmpeg_missing or sys.platform.startswith("linux"):
            for command in system_commands(sys.platform):
                execute(command)
    if git:
        execute([git, "submodule", "update", "--init", "--recursive"])
    for required in ("backend/app_center/creation_master/react/package.json", "teaching_data/README.md"):
        if not args.dry_run and not (ROOT / required).is_file():
            raise RuntimeError(f"Missing submodule file: {required}. Initialize the pinned submodules first.")

    pip = [sys.executable, "-m", "pip"]
    execute(pip + ["install", "--upgrade", "pip", "wheel"])
    profile = "development" if args.development else "production"
    execute(pip + ["install", "-r", ROOT / f"backend/requirements/{profile}.txt"])
    if args.with_creation_master:
        execute(pip + ["install", "-r", ROOT / "backend/app_center/creation_master/requirements.txt"])
    execute(pip + ["check"])
    if "dtk" in runtimes:
        install_dtk(execute)
    # App Center React sources share the root frontend's dependencies and aliases.
    # Include dev dependencies even under NODE_ENV=production: Vite/tsc need them.
    folders = [ROOT / "frontend"]
    if "png" in runtimes:
        folders.append(PNG)
    if "animation" in runtimes:
        folders.append(ANIMATION)
    if args.with_mobile:
        folders.append(ROOT / "mobile")
    for folder in folders:
        execute(npm + ["ci", "--include=dev"], cwd=folder)
    if args.with_codex:
        execute(npm + ["install", "--global", f"@openai/codex@{CODEX_VERSION}"])

    if "png" in runtimes:
        install_png(execute, node, system_deps=args.system_deps)
    if "animation" in runtimes:
        install_animation(execute, node, npm)
    if args.with_creation_master:
        execute([sys.executable, "-m", "playwright", "install", "chromium"])
    print("\nDependency installation plan complete." if args.dry_run else "\nRepository dependencies installed; selected runtimes verified.")
    if ffmpeg_missing and args.system_deps and sys.platform == "win32":
        print("Open a new terminal so the FFmpeg PATH update takes effect before starting workers.")
    print("Configure backend/.env and service credentials, then run migrations/start services separately.")
    for name in selected:
        for note in catalog[name].get("notes", []):
            print(f"[{name}] {note}")
        if catalog[name].get("skills"):
            print(f"[{name}] External Skills: " + ", ".join(catalog[name]["skills"]))
    if "png" in runtimes:
        print("If backend/.env sets PLAYWRIGHT_NODE_MODULES, remove stale host paths or point it at " + str(PNG / "node_modules"))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"\nInstallation failed: {error}", file=sys.stderr)
        sys.exit(1)

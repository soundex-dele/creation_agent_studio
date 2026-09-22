"""Install repository dependencies using the project virtual environment only."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PNG = ROOT / "backend/app_center/html_to_png"
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", help="Include test/development Python packages")
    parser.add_argument("--system-deps", action="store_true", help="Install FFmpeg and Linux Chromium system libraries (may require admin/sudo)")
    parser.add_argument("--with-creation-master", action="store_true", help="Install optional Windows Creation Master desktop Python packages")
    parser.add_argument("--with-mobile", action="store_true", help="Install mobile npm packages (not Android/iOS SDKs)")
    parser.add_argument("--with-codex", action="store_true", help="Install the pinned Codex CLI globally")
    parser.add_argument("--skip-submodules", action="store_true", help="Use already initialized submodules or a source archive")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without changing files or installing packages")
    args = parser.parse_args(argv)

    allowed_venvs = {(ROOT / "backend/venv").resolve(), (ROOT / "backend/.venv").resolve()}
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() not in allowed_venvs:
        raise RuntimeError("Use install-dependencies.ps1/.sh or the backend project virtual environment.")
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required; Python 3.12 is recommended.")
    if args.with_creation_master and sys.platform != "win32":
        raise RuntimeError("Creation Master's desktop requirements include Windows automation; use this option on Windows only.")
    node = require_program("node")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    major, minor = (int(value) for value in version.lstrip("v").split(".")[:2])
    if not ((major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major >= 24):
        raise RuntimeError(f"Node {version} is unsupported. Install Node.js 22.12+ LTS or 24 LTS.")
    npm = npm_command(node)
    git = require_program("git") if not args.skip_submodules else None
    execute = lambda command, **kwargs: run(command, dry_run=args.dry_run, **kwargs)
    ffmpeg_missing = not shutil.which("ffmpeg") or not shutil.which("ffprobe")
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
    # App Center React sources share the root frontend's dependencies and aliases.
    # Include dev dependencies even under NODE_ENV=production: Vite/tsc need them.
    for folder in ([ROOT / "frontend", PNG] + ([ROOT / "mobile"] if args.with_mobile else [])):
        execute(npm + ["ci", "--include=dev"], cwd=folder)
    if args.with_codex:
        execute(npm + ["install", "--global", f"@openai/codex@{CODEX_VERSION}"])

    playwright_cli = PNG / "node_modules/playwright/cli.js"
    browser_args = ["install", "chromium"]
    if args.system_deps and sys.platform.startswith("linux"):
        browser_args.append("--with-deps")
    # Install into Playwright's normal per-user cache. Run as the service account.
    execute([node, playwright_cli, *browser_args], cwd=PNG)
    if args.with_creation_master:
        execute([sys.executable, "-m", "playwright", "install", "chromium"])
    smoke = (
        "const {chromium}=require('playwright'); "
        "(async()=>{const b=await chromium.launch({headless:true}); "
        "try {const p=await b.newPage(); await p.setContent('<h1>Ready</h1>'); "
        "await p.screenshot(); console.log('Chromium PNG check passed');} "
        "finally {await b.close();}})().catch(e=>{console.error(e);process.exit(1)});"
    )
    execute([node, "-e", smoke], cwd=PNG)
    print("\nDependency installation plan complete." if args.dry_run else "\nDependencies installed and Chromium verified.")
    if ffmpeg_missing and args.system_deps and sys.platform == "win32":
        print("Open a new terminal so the FFmpeg PATH update takes effect before starting workers.")
    print("Configure backend/.env and service credentials, then run migrations/start services separately.")
    print("External Skill directories and their own dependencies must be provisioned on the execution host.")
    print("If backend/.env sets PLAYWRIGHT_NODE_MODULES, remove stale host paths or point it at " + str(PNG / "node_modules"))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"\nInstallation failed: {error}", file=sys.stderr)
        sys.exit(1)

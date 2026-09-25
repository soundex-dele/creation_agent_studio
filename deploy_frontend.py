#!/usr/bin/env python3
"""Build, compress and upload the frontend, then extract it on the server."""

import argparse
from contextlib import nullcontext
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from uuid import uuid4


FRONTEND = Path(__file__).resolve().parent / "frontend"
REMOTE = "root@47.120.21.129"
REMOTE_DIR = "/root/creation_agent_studio/frontend"


def run(command, *, cwd=None, dry_run=False):
    print(f"+ {shlex.join(command)}", flush=True)
    if not dry_run:
        subprocess.run(command, cwd=cwd, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("-i", "--identity", type=Path, help="SSH private key path")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without building or uploading")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    programs = {}
    for name in ("npm", "ssh", "scp"):
        programs[name] = shutil.which(name)
        if not programs[name]:
            raise RuntimeError(f"找不到 {name}，请先安装 Node.js/npm 和 OpenSSH 并加入 PATH。")
    if not (FRONTEND / "package.json").is_file():
        raise RuntimeError(f"找不到前端配置：{FRONTEND / 'package.json'}")

    options = ["-o", "ConnectTimeout=15"]
    if args.identity:
        identity = args.identity.expanduser().resolve()
        if not identity.is_file():
            raise RuntimeError(f"找不到 SSH 私钥：{identity}")
        options += ["-i", str(identity)]

    print(f"构建目录：{FRONTEND}", flush=True)
    run([programs["npm"], "run", "build"], cwd=FRONTEND, dry_run=args.dry_run)
    dist = FRONTEND / "dist"
    if not args.dry_run and not (dist / "index.html").is_file():
        raise RuntimeError(f"构建后找不到 {dist / 'index.html'}，停止上传。")

    ssh = [programs["ssh"], *options, "-p", str(args.port), REMOTE]
    # A unique name avoids collisions between concurrent uploads.
    archive_name = f".frontend-dist-{uuid4().hex}.tar.gz"
    remote_archive = f"{REMOTE_DIR}/{archive_name}"
    temporary = (
        nullcontext(str(Path(tempfile.gettempdir()) / "frontend-deploy-preview"))
        if args.dry_run else tempfile.TemporaryDirectory(prefix="frontend-deploy-")
    )
    with temporary as temp_dir:
        archive = Path(temp_dir) / archive_name
        print(f"压缩：{dist} -> {archive}", flush=True)
        if not args.dry_run:
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(dist, arcname="dist")
            print(f"压缩包大小：{archive.stat().st_size / 1024 / 1024:.2f} MB", flush=True)

        run(
            [*ssh, f"mkdir -p -- {shlex.quote(REMOTE_DIR)}"],
            dry_run=args.dry_run,
        )
        run(
            [programs["scp"], *options, "-P", str(args.port), str(archive),
             f"{REMOTE}:{remote_archive}"],
            dry_run=args.dry_run,
        )
        # The archive contains dist/, so extraction produces frontend/dist/.
        # Retain the remote archive on extraction failure for troubleshooting.
        run(
            [*ssh, f"tar -xzf {shlex.quote(remote_archive)} -C {shlex.quote(REMOTE_DIR)}"
             f" && rm -f -- {shlex.quote(remote_archive)}"],
            dry_run=args.dry_run,
        )
    if args.dry_run:
        print("预览完成，未执行构建或上传。")
    else:
        print(f"部署完成：{REMOTE}:{REMOTE_DIR}/dist")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"命令执行失败（退出码 {exc.returncode}），部署已停止。", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError, tarfile.TarError) as exc:
        print(f"部署失败：{exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n部署已取消。", file=sys.stderr)
        sys.exit(130)

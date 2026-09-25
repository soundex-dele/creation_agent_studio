#!/usr/bin/env python3
"""Push the current Git commit to the server and update its working tree."""

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REMOTE = "root@47.120.21.129"
REMOTE_DIR = "/root/creation_agent_studio"


def run(command, *, dry_run=False, **kwargs):
    print(f"+ {shlex.join(command)}", flush=True)
    if not dry_run:
        subprocess.run(command, check=True, **kwargs)


def prepare_command(branch):
    """Configure a non-bare checkout; never reset existing server changes."""
    directory = shlex.quote(REMOTE_DIR)
    ref = shlex.quote(f"refs/heads/{branch}")
    return f"""set -eu
mkdir -p -- {directory}
cd -- {directory}
if [ ! -e .git ]; then
    git init .
    git symbolic-ref HEAD {ref}
fi
if [ "$(git rev-parse --is-bare-repository)" != false ] || [ "$(git rev-parse --show-prefix)" != '' ]; then
    echo '目标目录必须是普通 Git 仓库的根目录。' >&2
    exit 1
fi
if [ "$(git symbolic-ref -q HEAD)" != {ref} ]; then
    echo '服务器当前分支与 --branch 不一致，请指定服务器当前分支后重试。' >&2
    git symbolic-ref --short HEAD >&2
    exit 1
fi
git config --local receive.denyCurrentBranch updateInstead
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="main", help="Server checkout branch (default: main)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("-i", "--identity", type=Path, help="SSH private key path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without connecting or pushing")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    git = shutil.which("git")
    ssh = shutil.which("ssh")
    if not git or not ssh:
        raise RuntimeError("请先安装 Git 和 OpenSSH 并加入 PATH。")
    # Validate before embedding the ref into a remote command or refspec.
    subprocess.run([git, "check-ref-format", f"refs/heads/{args.branch}"], check=True)
    repository = subprocess.check_output(
        [git, "rev-parse", "--show-toplevel"], cwd=ROOT, text=True,
    ).strip()
    if Path(repository).resolve() != ROOT.resolve():
        raise RuntimeError("脚本必须位于待推送 Git 仓库的根目录。")
    commit = subprocess.check_output(
        [git, "rev-parse", "--verify", "HEAD^{commit}"], cwd=ROOT, text=True,
    ).strip()
    if subprocess.check_output([git, "status", "--porcelain"], cwd=ROOT):
        print("提示：存在未提交修改，本次仅推送已提交代码，请先提交需要部署的修改。", flush=True)

    ssh_command = [ssh, "-o", "ConnectTimeout=15", "-p", str(args.port)]
    if args.identity:
        identity = args.identity.expanduser().resolve()
        if not identity.is_file():
            raise RuntimeError(f"找不到 SSH 私钥：{identity}")
        ssh_command += ["-i", str(identity)]
    environment = os.environ.copy()
    # Git parses GIT_SSH_COMMAND using a shell, including on Git for Windows.
    environment["GIT_SSH_COMMAND"] = shlex.join(ssh_command)
    environment["GIT_SSH_VARIANT"] = "ssh"
    print(f"推送提交：{commit}\n目标：{REMOTE}:{REMOTE_DIR}（分支 {args.branch}）", flush=True)
    run([*ssh_command, REMOTE, prepare_command(args.branch)], dry_run=args.dry_run)
    # Pin the commit inspected above so a concurrent local commit cannot change this deployment.
    run(
        [git, "push", f"{REMOTE}:{REMOTE_DIR}", f"{commit}:refs/heads/{args.branch}"],
        cwd=ROOT, env=environment, dry_run=args.dry_run,
    )
    run(
        [*ssh_command, REMOTE,
         f"cd -- {shlex.quote(REMOTE_DIR)} && git submodule sync --recursive"
         " && git submodule update --init --recursive"],
        dry_run=args.dry_run,
    )
    print("预览完成，未连接服务器。" if args.dry_run else "代码推送及子模块同步完成。")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"命令失败（退出码 {exc.returncode}），后续操作已停止。请查看上方错误。", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as exc:
        print(f"推送失败：{exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n推送已取消。", file=sys.stderr)
        sys.exit(130)

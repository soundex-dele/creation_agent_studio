"""Shared OpenSSH key setup for the deployment entry points."""

from pathlib import Path
import shlex
import shutil
import subprocess


def default_identity():
    return Path.home() / ".ssh" / "creation_agent_studio_ed25519"


def ssh_options(identity=None):
    options = ["-o", "ConnectTimeout=15"]
    key = identity.expanduser().resolve() if identity else default_identity()
    if identity or key.is_file():
        if not key.is_file():
            raise RuntimeError(f"找不到 SSH 私钥：{key}")
        options += ["-i", str(key), "-o", "IdentitiesOnly=yes"]
    return options


# Read the public key from stdin; preserve existing authorized keys and avoid duplicates.
INSTALL_KEY = """set -eu
umask 077
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
IFS= read -r key
if ! grep -qxF -- "$key" "$HOME/.ssh/authorized_keys"; then
    printf '\\n%s\\n' "$key" >> "$HOME/.ssh/authorized_keys"
fi
"""


def setup_ssh(ssh, remote, port, identity=None, *, dry_run=False):
    key = identity.expanduser().resolve() if identity else default_identity()
    if identity and not key.is_file():
        raise RuntimeError(f"找不到 SSH 私钥：{key}")
    print(f"免密登录私钥：{key}", flush=True)
    if dry_run:
        print(f"预览：按需生成专用密钥，将公钥安装到 {remote}（端口 {port}），再验证免密登录。")
        print("未生成密钥或连接服务器。")
        return
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise RuntimeError("找不到 ssh-keygen，请先安装 OpenSSH 并加入 PATH。")
    if not key.is_file():
        # Do not replace a leftover public key or any existing private-key path.
        if key.exists() or Path(str(key) + ".pub").exists():
            raise RuntimeError(f"密钥路径已存在，停止以避免覆盖：{key}")
        key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        subprocess.run(
            [keygen, "-t", "ed25519", "-N", "", "-C", "creation-agent-studio-deploy", "-f", str(key)],
            check=True,
        )
    # Derive from the private key instead of trusting a potentially stale .pub file.
    public_key = subprocess.check_output([keygen, "-y", "-f", str(key)], text=True).strip()
    if not public_key or "\n" in public_key or "\r" in public_key:
        raise RuntimeError("无法读取有效的 SSH 公钥。")
    command = [ssh, *ssh_options(key), "-p", str(port)]
    print("首次配置可能需要输入一次服务器密码（以及确认服务器指纹）。", flush=True)
    subprocess.run(
        [*command, "-o", "NumberOfPasswordPrompts=1", remote, INSTALL_KEY],
        # Binary stdin prevents Windows from turning LF into CRLF in authorized_keys.
        input=(public_key + "\n").encode("utf-8"), check=True,
    )
    result = subprocess.run(
        [*command, "-o", "BatchMode=yes", remote, "true"], check=False,
    )
    if result.returncode:
        raise RuntimeError("公钥已安装，但免密验证失败。请检查服务器公钥认证配置；加密私钥需先加载到 ssh-agent。")
    print("免密登录配置成功，deploy_frontend.py 和 push_code.py 均可复用。")
    if identity:
        print(f"后续运行时请继续指定 -i {shlex.quote(str(key))}。")

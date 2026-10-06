"""Stable, private workspace roots owned by application users."""
from pathlib import Path

from django.conf import settings


def user_directory(user) -> Path:
    if not user or not user.is_authenticated or user.pk is None or not user.is_active:
        raise PermissionError('需要有效的登录用户。')
    root = Path(settings.AGENT_WORKSPACE_ROOT).expanduser().resolve()
    # A symlink at either boundary must never merge two users' namespaces.
    users = root / 'users'
    target = users / str(user.pk)
    if users.is_symlink() or target.is_symlink():
        raise PermissionError('用户目录不能是符号链接。')
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    return target.resolve()

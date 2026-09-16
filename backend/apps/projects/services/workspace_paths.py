"""Safe filesystem workspace allocation for conversations and application runs."""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings


def _managed_root() -> Path:
    root = Path(settings.AGENT_WORKSPACE_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _scope_root(user, organization=None) -> Path:
    root = _managed_root()
    if organization is not None:
        target = root / 'organizations' / str(organization.id)
    else:
        target = root / 'users' / str(user.id)
    return _create_managed(target)


def _create_managed(target: Path) -> Path:
    root = _managed_root()
    resolved = target.expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError('Working directory escaped AGENT_WORKSPACE_ROOT.')
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def system_working_directory(
    user, organization=None, conversation_id=None,
) -> str:
    """Return the managed directory used by an ordinary system conversation."""
    scope = _scope_root(user, organization)
    target = (
        scope / 'conversations' / str(conversation_id)
        if conversation_id is not None
        else scope / 'system'
    )
    return str(_create_managed(target))


def application_working_directory(project) -> str:
    """Create or restore the directory owned by a standalone application run."""
    if project.working_directory:
        return str(_create_managed(Path(project.working_directory)))
    scope = _scope_root(project.user, project.organization)
    if project.application_id:
        target = (scope / 'applications' / project.application.slug
                  / str(project.id))
    else:
        target = scope / 'projects' / str(project.id)
    project.working_directory = str(_create_managed(target))
    project.save(update_fields=['working_directory'])
    return project.working_directory


def validate_system_working_directory(raw_path: str) -> str:
    """Validate a user-selected server directory against configured roots."""
    target = Path(raw_path).expanduser().resolve(strict=False)
    roots = [
        Path(root).expanduser().resolve(strict=False)
        for root in settings.APPLICATION_RUNTIME_ALLOWED_ROOTS
    ]
    if not roots:
        raise ValueError('系统目录选择未启用。')
    if not any(target == root or root in target.parents for root in roots):
        raise ValueError('目录不在允许的系统工作区范围内。')
    if not target.is_dir():
        raise ValueError('所选系统工作目录不存在。')
    return str(target)


def conversation_working_directory(conversation) -> str:
    """Resolve and persist the effective directory for any conversation source."""
    # Only an ordinary conversation may own an explicitly selected external
    # system directory. Managed application/workflow directories are resolved
    # again so a directory removed on disk is safely recreated before a run.
    if (conversation.working_directory
            and not conversation.project_id
            and not conversation.application_id):
        current = Path(conversation.working_directory).expanduser().resolve(
            strict=False)
        legacy_default = (
            _scope_root(conversation.user, conversation.organization) / 'system'
        ).resolve(strict=False)
        if current != legacy_default:
            return conversation.working_directory
    if conversation.project_id:
        project = conversation.project
        if (
            conversation.application_id
            and project.application_id is None
            and not project.workflow_id
            and not project.working_directory
        ):
            project.application_id = conversation.application_id
            project.save(update_fields=['application'])
        path = application_working_directory(project)
    elif conversation.application_id:
        scope = _scope_root(conversation.user, conversation.organization)
        path = str(_create_managed(
            scope / 'applications' / conversation.application.slug
            / 'conversations' / str(conversation.id)))
    else:
        path = system_working_directory(
            conversation.user,
            conversation.organization,
            conversation.id,
        )
    if conversation.working_directory != path:
        conversation.working_directory = path
        conversation.save(update_fields=['working_directory'])
    return path


def open_workspace_directory(raw_path: str) -> None:
    """Open an existing workspace in the host operating system's file manager."""
    directory = Path(raw_path).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise FileNotFoundError(str(directory))
    if os.name == 'nt':
        os.startfile(str(directory))
        return

    command = ['open', str(directory)] if sys.platform == 'darwin' else [
        'xdg-open', str(directory),
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

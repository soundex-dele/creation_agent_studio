"""Safe filesystem workspace allocation for conversations and application runs."""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from apps.applications.runtime_paths import resolve_runtime_path
from core.user_directories import user_directory


def _managed_root() -> Path:
    root = Path(settings.AGENT_WORKSPACE_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _scope_root(user, organization=None) -> Path:
    # Organization membership never grants access to another user's files.
    return user_directory(user)


def _create_managed(target: Path, user) -> Path:
    root = _managed_root()
    resolved = target.expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError('Working directory escaped AGENT_WORKSPACE_ROOT.')
    try:
        resolve_runtime_path(str(resolved), user)
    except PermissionError as exc:
        raise PermissionDenied(str(exc)) from exc
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
    return str(_create_managed(target, user))


def application_working_directory(project) -> str:
    """Create or restore the directory owned by a standalone application run."""
    if project.scope == 'cowork' and project.directory_source == 'explicit':
        from rest_framework.exceptions import ValidationError
        try:
            return validate_system_working_directory(project.working_directory, project.user)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ValidationError({'working_directory': str(exc)}) from exc
    if project.working_directory:
        return str(_create_managed(Path(project.working_directory), project.user))
    scope = _scope_root(project.user, project.organization)
    if project.application_id:
        target = (scope / 'applications' / project.application.slug
                  / str(project.id))
    else:
        target = scope / 'projects' / str(project.id)
    project.working_directory = str(_create_managed(target, project.user))
    project.save(update_fields=['working_directory'])
    return project.working_directory


def workflow_working_directory(
    user, organization, run_id, *, working_directory=None,
) -> str:
    """Resolve the shared workspace, including one retained by a retried Run."""
    scope = _scope_root(user, organization) / 'workflows'
    target = scope / str(run_id)
    if working_directory:
        if not isinstance(working_directory, str):
            raise RuntimeError('Invalid workflow working directory.')
        target = Path(working_directory).expanduser().resolve()
        if scope not in target.parents:
            raise RuntimeError('Working directory escaped the workflow scope.')
    return str(_create_managed(target, user))


def validate_system_working_directory(raw_path: str, user) -> str:
    """Validate a selected directory against the authenticated user's scope."""
    target = resolve_runtime_path(raw_path, user)
    if not target.is_dir():
        raise ValueError('所选系统工作目录不存在。')
    return str(target)


def conversation_working_directory(conversation) -> str:
    """Resolve and persist the effective directory for any conversation source."""
    if conversation.scope == 'cowork':
        path = (application_working_directory(conversation.project)
                if conversation.project_id else system_working_directory(
                    conversation.user, conversation.organization, conversation.id))
        if conversation.working_directory != path:
            conversation.working_directory = path
            conversation.save(update_fields=['working_directory'])
        return path
    # Only an ordinary conversation may own an explicitly selected external
    # system directory. Managed application/workflow directories are resolved
    # again so a directory removed on disk is safely recreated before a run.
    if (conversation.working_directory
            and str(conversation.process_id or '').startswith('workflow:')):
        return str(_create_managed(Path(conversation.working_directory), conversation.user))
    if (conversation.working_directory
            and not conversation.project_id
            and not conversation.application_id):
        current = Path(conversation.working_directory).expanduser().resolve(
            strict=False)
        legacy_default = (
            _scope_root(conversation.user, conversation.organization) / 'system'
        ).resolve(strict=False)
        legacy_organization_default = (
            _managed_root() / 'organizations' / str(conversation.organization_id) / 'system'
        )
        if current not in (legacy_default, legacy_organization_default):
            try:
                return validate_system_working_directory(str(current), conversation.user)
            except PermissionError as exc:
                raise PermissionDenied(str(exc)) from exc
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
            / 'conversations' / str(conversation.id), conversation.user))
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

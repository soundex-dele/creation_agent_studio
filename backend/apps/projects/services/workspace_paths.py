"""Safe filesystem workspace allocation for conversations and application runs."""
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


def system_working_directory(user, organization=None) -> str:
    """Return the managed directory used by an ordinary system conversation."""
    return str(_create_managed(_scope_root(user, organization) / 'system'))


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


def workflow_working_directories(run) -> str:
    """Create the workflow directory first, then one child per application step."""
    scope = _scope_root(run.started_by, run.organization)
    workflow_path = _create_managed(scope / 'workflows' / str(run.id))
    if run.working_directory != str(workflow_path):
        run.working_directory = str(workflow_path)
        run.save(update_fields=['working_directory'])
    if run.project.working_directory != str(workflow_path):
        run.project.working_directory = str(workflow_path)
        run.project.save(update_fields=['working_directory'])

    apps_path = _create_managed(workflow_path / 'applications')
    for step_run in run.step_runs.select_related('application').all():
        step_path = _create_managed(
            apps_path / f'{step_run.order:03d}-{step_run.application.slug}')
        if step_run.working_directory != str(step_path):
            step_run.working_directory = str(step_path)
            step_run.save(update_fields=['working_directory'])
    return str(workflow_path)


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
            and not conversation.workflow_step_run_id
            and not conversation.project_id
            and not conversation.application_id):
        return conversation.working_directory
    if conversation.workflow_step_run_id:
        step_run = conversation.workflow_step_run
        if not step_run.working_directory:
            workflow_working_directories(step_run.workflow_run)
            step_run.refresh_from_db(fields=['working_directory'])
        path = step_run.working_directory
    elif conversation.project_id:
        project = conversation.project
        if (
            conversation.application_id
            and project.application_id is None
            and not (project.structure or {}).get('workflow_id')
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
            conversation.user, conversation.organization)
    if conversation.working_directory != path:
        conversation.working_directory = path
        conversation.save(update_fields=['working_directory'])
    return path

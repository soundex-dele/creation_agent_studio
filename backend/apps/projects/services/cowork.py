"""Explicit folder bindings. Directory allocation alone never creates a project."""
import hashlib
import os
from pathlib import Path

from rest_framework.exceptions import ValidationError

from apps.projects.models import Project
from .workspace_paths import validate_system_working_directory


def resource_scope(request):
    scope = request.query_params.get('scope', 'default')
    if scope not in ('default', 'cowork'):
        raise ValidationError({'scope': '未知的工作空间范围。'})
    return scope


def bind_directory(user, organization, directory, title=''):
    try:
        path = validate_system_working_directory(directory)
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValidationError({'working_directory': str(exc)}) from exc
    key = hashlib.sha256(os.path.normcase(path).encode('utf-8')).hexdigest()
    project, _ = Project.objects.get_or_create(
        organization=organization, user=user, scope='cowork', directory_key=key,
        defaults={'title': title.strip() or (Path(path).name or path)[:200],
                  'working_directory': path, 'directory_source': 'explicit'},
    )
    return project

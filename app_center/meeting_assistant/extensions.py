"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'meeting-assistant':
        return None
    if not user.is_authenticated or run.owner_id != user.id:
        return False
    from django.http import Http404
    from django.core.exceptions import ValidationError
    from rest_framework.exceptions import APIException
    from .backend.access import recording_for
    try:
        recording_for(user, run.organization_id, run.source_id, (run.input or {}).get('record_id'))
    except (Http404, APIException, ValueError, ValidationError):
        return False
    return True


provider = ApplicationContributions(run_access=run_access, run_access_input_keys=('record_id',))

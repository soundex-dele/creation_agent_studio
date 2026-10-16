"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'animation-studio':
        return None
    if not user.is_authenticated or run.owner_id != user.id:
        return False
    from django.http import Http404
    from django.core.exceptions import ValidationError
    from rest_framework.exceptions import APIException
    from .backend.access import application_for
    try:
        application_for(user, run.organization_id, run.source_id)
    except (Http404, APIException, ValueError, ValidationError):
        return False
    return True


def run_access_many(user, roots):
    from modules.platform_api.identity import active_member_applications
    runs = [run for run in roots if run.executor_key == 'animation-studio']
    if not runs:
        return {}
    allowed = {(org, str(pk)) for org, pk in active_member_applications(
        user, {run.organization_id for run in runs}, slug='animation-studio',
    ).values_list('organization_id', 'id')}
    return {run.pk: run.owner_id == user.pk and (run.organization_id, run.source_id) in allowed
            for run in runs}


provider = ApplicationContributions(run_access=run_access, run_access_many=run_access_many, run_access_input_keys=())

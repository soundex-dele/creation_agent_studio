from django.http import Http404
from django.core.exceptions import ValidationError
from rest_framework.exceptions import APIException
from modules.platform_api.extensions import ApplicationContributions
from .backend.access import application_for


def run_access(user, run):
    if run.executor_key != "web-fetch":
        return None
    if not user.is_authenticated or run.owner_id != user.id:
        return False
    try:
        application_for(user, run.organization_id, run.source_id)
    except (Http404, APIException, ValidationError, ValueError):
        return False
    return True


provider = ApplicationContributions(run_access=run_access, run_access_input_keys=())

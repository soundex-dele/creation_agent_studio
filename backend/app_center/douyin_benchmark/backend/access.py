from django.shortcuts import get_object_or_404
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from rest_framework.exceptions import PermissionDenied
from .models import Account, Task


def application_for(user, organization_id, application_id):
    if not Membership.objects.filter(organization_id=organization_id, organization__is_active=True,
            user=user, user__is_active=True, is_active=True).exists():
        raise PermissionDenied("当前账号不再是有效组织成员。")
    apps = accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug="douyin-benchmark", kind="custom", is_active=True), user, operation="run")
    return get_object_or_404(apps, pk=application_id)


def account_for(user, organization_id, application_id, pk, *, lock=False):
    app = application_for(user, organization_id, application_id)
    qs = Account.objects.filter(application=app, owner=user, organization_id=organization_id)
    return get_object_or_404(qs.select_for_update() if lock else qs, pk=pk)


def can_access_run(user, run):
    from django.http import Http404
    from django.core.exceptions import ValidationError
    from rest_framework.exceptions import APIException
    if user.id != run.owner_id:
        return False
    try:
        task = Task.objects.get(pk=run.input.get("task_id"), run=run)
        account_for(user, run.organization_id, run.source_id, task.account_id)
        return True
    except (Task.DoesNotExist, Http404, APIException, ValueError, ValidationError):
        return False

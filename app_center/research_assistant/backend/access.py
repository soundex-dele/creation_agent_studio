from django.shortcuts import get_object_or_404
from django.db import connection
from django.db.models import F
from rest_framework.exceptions import PermissionDenied
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from .models import ResearchProject


def application_for(user, organization_id, application_id):
    if not user.is_active or not Membership.objects.filter(
        organization_id=organization_id, organization__is_active=True, user=user, is_active=True,
    ).exists():
        raise PermissionDenied("当前账号不再是有效组织成员。")
    return get_object_or_404(accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug="research-assistant", kind="custom", is_active=True), user, operation="run"), pk=application_id)


def project_for(user, organization_id, application_id, pk, *, lock=False, deleted=False):
    application_for(user, organization_id, application_id)
    qs = ResearchProject.objects.filter(organization_id=organization_id, application_id=application_id, owner=user)
    if not deleted:
        qs = qs.filter(deleted_at__isnull=True)
    if lock:
        if connection.vendor == "sqlite":
            qs.filter(pk=pk).update(title=F("title"))
        qs = qs.select_for_update()
    return get_object_or_404(qs, pk=pk)


def can_access_run(user, run):
    """None means unrelated; False also covers orphaned/deleted project runs."""
    from django.core.exceptions import ValidationError
    from django.http import Http404
    from rest_framework.exceptions import APIException
    project_id = (run.input or {}).get("research_project_id")
    if not project_id and run.executor_key != "research-assistant":
        return None
    if not user.is_authenticated or run.owner_id != user.id or not project_id:
        return False
    try:
        project = ResearchProject.objects.get(pk=project_id, organization_id=run.organization_id,
                                              owner=user, deleted_at__isnull=True)
        application_for(user, run.organization_id, project.application_id)
        return True
    except (ResearchProject.DoesNotExist, Http404, APIException, ValueError, ValidationError):
        return False

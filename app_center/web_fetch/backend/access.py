from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from modules.platform_api.identity import Application, Membership, accessible_resources
from modules.platform_api.execution import Run


def application_for(user, organization_id, application_id):
    if not Membership.objects.filter(organization_id=organization_id, organization__is_active=True,
                                     user=user, user__is_active=True, is_active=True).exists():
        raise PermissionDenied("当前账号不是有效组织成员。")
    return get_object_or_404(accessible_resources(
        Application.objects.for_organization(organization_id).filter(
            slug="web-fetch", kind="custom", is_active=True), user, operation="run"), pk=application_id)


def runs_for(user, application):
    return Run.objects.for_organization(application.organization_id).filter(
        owner=user, source_type="application", source_id=str(application.id), executor_key="web-fetch")

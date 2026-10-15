from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.applications.models import Application
from core.resource_access import accessible_resources
from modules.tenancy.permissions import resolve_path_organization


def application_for(request, organization_id, application_id):
    user = request.user
    if not user or not user.is_authenticated or not user.is_active or not (user.is_superuser or user.role == "admin"):
        raise PermissionDenied("仅平台管理员可以使用磁盘清理大师。")
    if resolve_path_organization(request, organization_id) is None:
        raise PermissionDenied("无法访问该组织。")
    return get_object_or_404(accessible_resources(
        Application.objects.for_organization(organization_id).filter(slug="disk-cleaner", kind="custom", is_active=True),
        user, operation="run"), pk=application_id)

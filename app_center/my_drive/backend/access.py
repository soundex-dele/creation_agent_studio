from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from .models import DriveSpace


def application_for(user, organization_id, application_id):
    if not user.is_active or not Membership.objects.filter(
        organization_id=organization_id, organization__is_active=True, user=user, is_active=True,
    ).exists():
        raise PermissionDenied("当前账号不再是有效组织成员。")
    return get_object_or_404(accessible_resources(
        Application.objects.for_organization(organization_id).filter(slug="my-drive", kind="custom", is_active=True),
        user, operation="run"), pk=application_id)


def space_for(user, organization_id):
    return DriveSpace.objects.get_or_create(owner=user, organization_id=organization_id)[0]

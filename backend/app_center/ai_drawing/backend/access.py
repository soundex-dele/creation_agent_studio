from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.execution.models import Run, RunArtifact
from .models import DrawingReference


def application_for(user, organization_id, application_id):
    if not Membership.objects.filter(organization_id=organization_id, organization__is_active=True,
                                     user=user, user__is_active=True, is_active=True).exists():
        raise PermissionDenied("当前账号不是有效组织成员。")
    return get_object_or_404(accessible_resources(
        Application.objects.for_organization(organization_id).filter(
            slug="ai-drawing", kind="custom", is_active=True), user, operation="run"), pk=application_id)


def drawings_for(user, application):
    return Run.objects.for_organization(application.organization_id).filter(
        owner=user, source_type="application", source_id=str(application.id), executor_key="ai-drawing")


def reference_for(user, application, reference_id):
    return get_object_or_404(DrawingReference.objects.for_organization(application.organization_id),
                             pk=reference_id, owner=user, application=application)


def source_for(user, application, artifact_id):
    return get_object_or_404(RunArtifact.objects.for_organization(application.organization_id),
                             pk=artifact_id, run__in=drawings_for(user, application), kind="drawing")

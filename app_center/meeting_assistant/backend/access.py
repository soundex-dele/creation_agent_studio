from uuid import UUID
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from .models import Recording


def application_for(user, organization_id, application_id=None, slug="meeting-assistant"):
    if not Membership.objects.filter(organization_id=organization_id, organization__is_active=True,
                                     user=user, user__is_active=True, is_active=True).exists():
        raise PermissionDenied("当前账号不再是有效组织成员。")
    queryset = accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug=slug, kind="custom", is_active=True), user, operation="run")
    return get_object_or_404(queryset, **({"pk": application_id} if application_id is not None else {}))


def recording_for(user, organization_id, application_id, pk, *, lock=False):
    try:
        pk = UUID(str(pk))
    except (ValueError, TypeError, AttributeError):
        raise Http404("录音不存在。")
    app = application_for(user, organization_id, application_id)
    queryset = Recording.objects.for_organization(organization_id).filter(application=app, owner=user)
    return get_object_or_404(queryset.select_for_update() if lock else queryset, pk=pk)

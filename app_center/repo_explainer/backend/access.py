from django.shortcuts import get_object_or_404
from django.db import connection
from django.db.models import F
from rest_framework.exceptions import PermissionDenied
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from .models import Project


def application_for(user, organization_id, application_id):
    if not user.is_active or not Membership.objects.filter(organization_id=organization_id,
            organization__is_active=True, user=user, is_active=True).exists():
        raise PermissionDenied('组织访问权限已失效。')
    return get_object_or_404(accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug='repo-explainer', is_active=True, kind='custom'), user, operation='run'), pk=application_id)


def project_for(user, organization_id, application_id, pk, lock=False):
    application_for(user, organization_id, application_id)
    qs = Project.objects.filter(organization_id=organization_id, application_id=application_id, owner=user)
    if lock and connection.vendor == 'sqlite':
        qs.filter(pk=pk).update(title=F('title'))
    return get_object_or_404(qs.select_for_update() if lock else qs, pk=pk)


def can_access_run(user, run):
    from django.core.exceptions import ValidationError
    from django.http import Http404
    from rest_framework.exceptions import APIException
    if run.owner_id != user.id:
        return False
    try:
        project_for(user, run.organization_id, run.source_id, run.input.get('repo_project_id'))
        return True
    except (Http404, APIException, ValueError, ValidationError):
        return False

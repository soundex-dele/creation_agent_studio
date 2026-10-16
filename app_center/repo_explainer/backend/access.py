from django.shortcuts import get_object_or_404
from django.db import connection
from django.db.models import F
from rest_framework.exceptions import PermissionDenied
from modules.platform_api.identity import Application
from modules.platform_api.identity import Membership
from modules.platform_api.identity import accessible_resources
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


def can_access_runs(user, runs):
    from uuid import UUID
    from modules.platform_api.identity import active_member_applications

    allowed_apps = set(active_member_applications(
        user, {run.organization_id for run in runs}, slug="repo-explainer",
    ).values_list("organization_id", "id"))
    project_ids = {}
    for run in runs:
        try:
            project_ids[run.pk] = UUID(str((run.input or {}).get('repo_project_id')))
        except (ValueError, TypeError):
            project_ids[run.pk] = None
    projects = {item["id"]: item for item in Project.objects.filter(
        pk__in=[pk for pk in project_ids.values() if pk], owner=user,
    ).values("id", "organization_id", "application_id")}
    return {run.pk: bool(
        run.owner_id == user.pk and (project := projects.get(project_ids[run.pk]))
        and project["organization_id"] == run.organization_id
        and str(project["application_id"]) == run.source_id
        and (run.organization_id, project["application_id"]) in allowed_apps
    ) for run in runs}


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

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
        application_for(user, run.organization_id, run.source_id)
        if task.owner_id != user.id or task.organization_id != run.organization_id or str(task.application_id) != str(run.source_id):
            return False
        if task.account_id:
            account_for(user, run.organization_id, run.source_id, task.account_id)
        return True
    except (Task.DoesNotExist, Http404, APIException, ValueError, ValidationError):
        return False


def can_access_knowledge_index(user, run, document):
    from django.http import Http404
    from rest_framework.exceptions import APIException
    from .models import CreationKnowledgeCard
    if run.owner_id != user.pk or document.is_deleted:
        return False
    card = CreationKnowledgeCard.objects.filter(document=document, owner=user,
        organization_id=run.organization_id, is_deleted=False).first()
    if card is None:
        return False
    try:
        application_for(user, run.organization_id, card.application_id)
        return True
    except (Http404, APIException, ValueError):
        return False

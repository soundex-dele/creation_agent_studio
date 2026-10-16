from django.shortcuts import get_object_or_404
from modules.platform_api.identity import Application
from modules.platform_api.identity import Membership
from modules.platform_api.identity import accessible_resources
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


def can_access_runs(user, runs):
    from uuid import UUID
    from modules.platform_api.identity import active_member_applications

    allowed_apps = set(active_member_applications(
        user, {run.organization_id for run in runs}, slug="douyin-benchmark",
    ).values_list("organization_id", "id"))
    tasks = {task["run_id"]: task for task in Task.objects.filter(
        run_id__in=[run.pk for run in runs], owner=user,
    ).values("id", "run_id", "organization_id", "application_id", "account_id",
             "account__owner_id", "account__organization_id", "account__application_id")}
    decisions = {}
    for run in runs:
        task = tasks.get(run.pk)
        try:
            task_id = UUID(str((run.input or {}).get("task_id")))
        except (ValueError, TypeError):
            task_id = None
        decisions[run.pk] = bool(
            run.owner_id == user.pk and task and task["id"] == task_id
            and task["organization_id"] == run.organization_id
            and str(task["application_id"]) == run.source_id
            and (run.organization_id, task["application_id"]) in allowed_apps
            and (not task["account_id"] or (
                task["account__owner_id"] == user.pk
                and task["account__organization_id"] == run.organization_id
                and task["account__application_id"] == task["application_id"]
            ))
        )
    return decisions


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

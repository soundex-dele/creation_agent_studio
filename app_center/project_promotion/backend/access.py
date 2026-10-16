from modules.platform_api.identity import Application
from modules.platform_api.identity import Membership
from modules.platform_api.identity import accessible_resources
from .models import AITask


def can_access_runs(user, runs):
    from modules.platform_api.identity import active_member_applications

    allowed_apps = set(active_member_applications(
        user, {run.organization_id for run in runs}, slug="project-promotion",
    ).values_list("organization_id", "id"))
    tasks = {task["run_id"]: task for task in AITask.objects.filter(
        run_id__in=[run.pk for run in runs], owner=user,
    ).values("run_id", "organization_id", "application_id")}
    return {run.pk: bool(
        run.owner_id == user.pk and (task := tasks.get(run.pk))
        and task["organization_id"] == run.organization_id
        and str(task["application_id"]) == run.source_id
        and (run.organization_id, task["application_id"]) in allowed_apps
    ) for run in runs}


def can_access_run(user, run):
    if run.owner_id != user.id or not user.is_active:
        return False
    if not Membership.objects.filter(organization_id=run.organization_id, organization__is_active=True,
                                     user=user, is_active=True).exists():
        return False
    task = AITask.objects.filter(run=run, owner=user, organization_id=run.organization_id).first()
    if not task or str(task.application_id) != run.source_id:
        return False
    return accessible_resources(Application.objects.for_organization(run.organization_id).filter(
        pk=task.application_id, slug='project-promotion', kind='custom', is_active=True), user, operation='run').exists()

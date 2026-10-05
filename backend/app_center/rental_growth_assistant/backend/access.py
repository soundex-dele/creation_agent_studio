"""The public execution API must preserve the application's private boundary."""
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from .models import AITask


def can_access_run(user, run):
    if run.owner_id != user.id or not user.is_active:
        return False
    if not Membership.objects.filter(organization_id=run.organization_id, organization__is_active=True,
                                     user=user, is_active=True).exists():
        return False
    task = AITask.objects.filter(run=run, organization_id=run.organization_id, owner=user).first()
    if task is None or str(task.application_id) != str(run.source_id):
        return False
    return accessible_resources(Application.objects.for_organization(run.organization_id).filter(
        pk=task.application_id, slug='rental-growth-assistant', kind='custom', is_active=True),
        user, operation='run').exists()

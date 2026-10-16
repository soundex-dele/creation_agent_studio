"""Kitchen-owned policies used by the application host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'kitchen-assistant':
        return None
    from .backend.models import KitchenAITask
    from modules.platform_api.identity import Application, accessible_resources, Membership
    if user.pk != run.owner_id:
        return False
    return (
        Membership.objects.filter(organization_id=run.organization_id, user=user,
                                  is_active=True, organization__is_active=True, user__is_active=True).exists()
        and accessible_resources(Application.objects.for_organization(run.organization_id).filter(
            pk=run.source_id, slug='kitchen-assistant', is_active=True), user, operation='run').exists()
        and KitchenAITask.objects.filter(run=run, state__owner=user,
            state__organization_id=run.organization_id, state__application_id=run.source_id).exists()
    )


provider = ApplicationContributions(run_access=run_access, run_access_input_keys=())

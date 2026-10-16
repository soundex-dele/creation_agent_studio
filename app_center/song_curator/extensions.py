from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'song-curator':
        return None
    from .backend.models import MusicTask
    from modules.platform_api.identity import Application, Membership, accessible_resources
    return bool(user.pk == run.owner_id and Membership.objects.filter(
        organization_id=run.organization_id, user=user, is_active=True,
        organization__is_active=True, user__is_active=True).exists()
        and accessible_resources(Application.objects.for_organization(run.organization_id).filter(
            pk=run.source_id, slug='song-curator', is_active=True), user, operation='run').exists()
        and MusicTask.objects.filter(run=run, library__owner=user, deleted=False,
            library__organization_id=run.organization_id, library__application_id=run.source_id).exists())


provider = ApplicationContributions(run_access=run_access, run_access_input_keys=())

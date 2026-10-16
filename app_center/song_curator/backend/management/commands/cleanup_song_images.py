from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from modules.platform_api.artifacts import get_artifact_storage
from modules.platform_api.identity import Membership
from modules.platform_api.tenancy import tenant_database_context
from app_center.song_curator.backend.models import MusicImage
from django.db.models import Q


class Command(BaseCommand):
    help = 'Clean deleted task images and unattached uploads older than 24 hours.'

    def handle(self, *args, **options):
        failed = 0
        organizations = Membership.objects.values_list('organization_id', flat=True).distinct()
        for organization_id in organizations:
            with tenant_database_context(organization_id):
                rows = MusicImage.objects.for_organization(organization_id).filter(
                    Q(task__deleted=True) | Q(task__isnull=True, created_at__lt=timezone.now() - timedelta(hours=24)))
                for image in rows:
                    try:
                        get_artifact_storage().delete(image.object_key)
                        image.delete()
                    except Exception:
                        failed += 1
                        self.stderr.write(f'Image cleanup pending: {image.pk}')
        if failed:
            raise CommandError(f'{failed} images still need cleanup.')

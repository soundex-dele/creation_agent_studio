from django.core.management.base import BaseCommand
from apps.enterprise.models import Organization
from modules.tenancy.database import tenant_database_context
from ...models import Snapshot
from ...research import record_observation


class Command(BaseCommand):
    help = 'Idempotently backfill metric observations from historical collection snapshots.'

    def add_arguments(self, parser):
        parser.add_argument('--organization')

    def handle(self, **options):
        orgs = Organization.objects.all()
        if options.get('organization'):
            orgs = orgs.filter(pk=options['organization'])
        created = 0
        for org_id in orgs.values_list('pk', flat=True).iterator():
            with tenant_database_context(org_id):
                for snapshot in Snapshot.objects.filter(batch__organization_id=org_id).select_related('batch', 'work').iterator(chunk_size=500):
                    _, new = record_observation(snapshot.batch, snapshot.work, snapshot.data, snapshot.captured_at)
                    created += int(new)
        self.stdout.write(f'Created {created} observations.')

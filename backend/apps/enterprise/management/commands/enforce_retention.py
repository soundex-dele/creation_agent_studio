import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.conversations.models import Conversation
from apps.enterprise.models import (
    AuditLog, EvaluationRun, GovernancePolicy, RunTrace, UsageRecord,
)
from modules.execution.application.event_retention import compact_eligible_runs
from modules.execution.infrastructure.artifacts import (
    UnsafeArtifactObjectKey,
    delete_artifact_object,
)
from modules.execution.models import IdempotencyRecord, Run
from modules.tenancy.database import tenant_database_context


class Command(BaseCommand):
    help = 'Delete tenant data beyond configured retention windows.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--loop', action='store_true')
        parser.add_argument('--poll-interval', type=float, default=3600)

    def _delete_runs(self, organization, cutoff, dry_run):
        queryset = Run.objects.for_organization(organization.id).filter(
            status__in=(Run.Status.SUCCEEDED, Run.Status.FAILED, Run.Status.CANCELLED),
            finished_at__lt=cutoff,
        ).order_by('finished_at')
        count = queryset.count()
        if dry_run:
            return count
        deleted = 0
        for run in queryset.iterator():
            if not Run.objects.filter(pk=run.pk).exists():
                continue
            run_ids = [run.id]
            frontier = [run.id]
            while frontier:
                frontier = list(Run.objects.filter(
                    parent_id__in=frontier
                ).values_list('id', flat=True))
                run_ids.extend(frontier)
            object_keys = list(Run.objects.filter(
                id__in=run_ids
            ).values_list('artifacts__object_key', flat=True))
            try:
                _rows, deleted_by_model = run.delete()
            except ProtectedError:
                continue
            deleted_runs = deleted_by_model.get(Run._meta.label, 0)
            if not deleted_runs:
                continue
            deleted += deleted_runs
            for object_key in filter(None, object_keys):
                try:
                    delete_artifact_object(object_key)
                except (OSError, UnsafeArtifactObjectKey):
                    continue
        return deleted

    def _cycle(self, *, dry_run):
        total = 0
        for policy in GovernancePolicy.objects.select_related('organization'):
            cutoff = timezone.now() - timedelta(days=policy.retention_days)
            with tenant_database_context(policy.organization_id):
                querysets = [
                    Conversation.objects.filter(
                        organization=policy.organization, updated_at__lt=cutoff),
                    RunTrace.objects.filter(
                        organization=policy.organization, created_at__lt=cutoff),
                    AuditLog.objects.filter(
                        organization=policy.organization, created_at__lt=cutoff),
                    UsageRecord.objects.filter(
                        organization=policy.organization, created_at__lt=cutoff),
                    EvaluationRun.objects.filter(
                        suite__organization=policy.organization, created_at__lt=cutoff),
                    IdempotencyRecord.objects.for_organization(
                        policy.organization_id).filter(expires_at__lt=timezone.now()),
                ]
                for queryset in querysets:
                    count = queryset.count()
                    total += count
                    if not dry_run:
                        queryset.delete()
                total += self._delete_runs(
                    policy.organization, cutoff, dry_run
                )
                if not dry_run:
                    while compact_eligible_runs(
                        before=timezone.now() - timedelta(
                            days=settings.RUN_EVENT_RETENTION_DAYS),
                        batch_size=settings.RUN_EVENT_COMPACTION_BATCH_SIZE,
                        organization_id=policy.organization_id,
                    ):
                        pass
        return total

    def handle(self, *args, **options):
        if options['poll_interval'] < 60:
            raise CommandError('--poll-interval must be at least 60 seconds')
        while True:
            total = self._cycle(dry_run=options['dry_run'])
            cache.set('execution-maintenance', timezone.now().isoformat(), 7200)
            self.stdout.write(
                f'{"Would delete" if options["dry_run"] else "Deleted"} {total} records'
            )
            if not options['loop']:
                return
            time.sleep(options['poll_interval'])

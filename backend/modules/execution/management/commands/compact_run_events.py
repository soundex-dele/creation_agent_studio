from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from modules.execution.application.event_retention import compact_eligible_runs


class Command(BaseCommand):
    help = "Compact retained terminal Run events into durable client snapshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--before-days",
            type=int,
            default=getattr(settings, "RUN_EVENT_RETENTION_DAYS", 30),
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=getattr(settings, "RUN_EVENT_COMPACTION_BATCH_SIZE", 500),
        )
        parser.add_argument("--run-id")

    def handle(self, *args, **options):
        if options["before_days"] < 0:
            raise CommandError("--before-days must be non-negative")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be positive")
        before = timezone.now() - timedelta(days=options["before_days"])
        compacted = compact_eligible_runs(
            before=before,
            batch_size=options["batch_size"],
            run_id=options["run_id"],
        )
        self.stdout.write(self.style.SUCCESS(f"Compacted {compacted} run(s)."))

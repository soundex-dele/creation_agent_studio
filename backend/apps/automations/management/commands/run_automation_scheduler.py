import time

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from apps.automations.models import Automation, AutomationInvocation
from apps.automations.scheduling import (
    ScheduleValidationError,
    advance_after_due,
    latest_due_time,
)
from apps.automations.services import dispatch_automation
from modules.tenancy.database import tenant_database_context


class Command(BaseCommand):
    help = "Dispatch active scheduled automations."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-interval", type=float, default=30)

    def handle(self, *args, **options):
        while True:
            cache.set(
                "automation-scheduler",
                timezone.now().isoformat(),
                max(30, int(options["poll_interval"] * 3)),
            )
            self.dispatch_due()
            if options["once"]:
                return
            time.sleep(options["poll_interval"])

    def dispatch_due(self):
        now = timezone.now()
        candidates = list(Automation.objects.filter(
            status=Automation.Status.ACTIVE,
            trigger_type=Automation.TriggerType.SCHEDULE,
            next_run_at__lte=now,
        ).values_list("id", "organization_id")[:500])
        for automation_id, organization_id in candidates:
            with tenant_database_context(organization_id), transaction.atomic():
                queryset = Automation.objects.select_related(
                    "organization", "created_by", "application", "workflow"
                )
                if connection.vendor == "postgresql":
                    queryset = queryset.select_for_update(skip_locked=True)
                else:
                    queryset = queryset.select_for_update()
                automation = queryset.filter(
                    pk=automation_id,
                    status=Automation.Status.ACTIVE,
                    next_run_at__lte=now,
                ).first()
                if automation is None:
                    continue
                try:
                    scheduled_for = latest_due_time(automation, now)
                    next_run_at = advance_after_due(automation, now)
                except ScheduleValidationError as exc:
                    automation.status = Automation.Status.BLOCKED
                    automation.is_active = False
                    automation.next_run_at = None
                    automation.blocked_reason = str(exc)
                    automation.save(update_fields=(
                        "status", "is_active", "next_run_at", "blocked_reason",
                        "updated_at",
                    ))
                    continue
                automation.last_scheduled_at = scheduled_for
                automation.next_run_at = next_run_at
                if next_run_at is None:
                    automation.status = Automation.Status.PAUSED
                    automation.is_active = False
                automation.save(update_fields=(
                    "last_scheduled_at", "next_run_at", "status", "is_active",
                    "updated_at",
                ))
                dispatch_automation(
                    automation,
                    source=AutomationInvocation.Source.SCHEDULE,
                    payload={},
                    dedup_key=f"schedule:{scheduled_for.isoformat()}",
                    scheduled_for=scheduled_for,
                )

import time

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.enterprise.models import AutomationTrigger
from apps.enterprise.services import cron_matches, dispatch_automation


class Command(BaseCommand):
    help = 'Dispatch active scheduled automations.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--poll-interval', type=float, default=30)

    def handle(self, *args, **options):
        while True:
            cache.set(
                'automation-scheduler',
                timezone.now().isoformat(),
                max(30, int(options['poll_interval'] * 3)),
            )
            now = timezone.now().replace(second=0, microsecond=0)
            trigger_ids = AutomationTrigger.objects.filter(
                is_active=True, trigger_type='schedule').values_list('id', flat=True)
            for trigger_id in trigger_ids:
                with transaction.atomic():
                    trigger = AutomationTrigger.objects.select_for_update().select_related(
                        'organization__owner').get(pk=trigger_id)
                    already_ran = trigger.last_triggered_at and \
                        trigger.last_triggered_at.replace(second=0, microsecond=0) >= now
                    if not already_ran and cron_matches(trigger.schedule, now):
                        dispatch_automation(
                            trigger, trigger.organization.owner, {}, scheduled_for=now)
            if options['once']:
                return
            time.sleep(options['poll_interval'])

from datetime import datetime, timedelta
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Check the WeChat connector scheduler heartbeat."

    def handle(self, *args, **options):
        value = cache.get("wechat-connector")
        if not value or timezone.now() - datetime.fromisoformat(value) > timedelta(seconds=90):
            raise CommandError("WeChat connector heartbeat missing or stale")

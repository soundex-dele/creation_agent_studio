from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Fail unless the requested execution worker or scheduler heartbeat is alive."

    def add_arguments(self, parser):
        parser.add_argument("--worker-pool")
        parser.add_argument("--scheduler", action="store_true")
        parser.add_argument("--maintenance", action="store_true")

    def handle(self, *args, **options):
        if options["maintenance"]:
            key = "execution-maintenance"
        elif options["scheduler"]:
            key = "automation-scheduler"
        elif options["worker_pool"]:
            key = f"execution-worker:{options['worker_pool']}"
        else:
            raise CommandError("Provide --worker-pool, --scheduler or --maintenance")
        if not cache.get(key):
            raise CommandError(f"Missing heartbeat: {key}")
        self.stdout.write(self.style.SUCCESS(f"Heartbeat is alive: {key}"))

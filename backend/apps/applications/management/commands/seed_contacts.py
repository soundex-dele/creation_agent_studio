"""Compatibility wrapper for the app-center contacts installer."""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Synchronize the bundled contacts application."

    def handle(self, *args, **options):
        call_command("sync_app_center", package_id="contacts", stdout=self.stdout)

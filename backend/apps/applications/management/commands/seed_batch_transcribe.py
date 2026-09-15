"""Compatibility wrapper for the app-center batch transcription installer."""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Synchronize the bundled batch-transcribe application.'

    def handle(self, *args, **options):
        call_command("sync_app_center", package_id="batch-transcribe", stdout=self.stdout)

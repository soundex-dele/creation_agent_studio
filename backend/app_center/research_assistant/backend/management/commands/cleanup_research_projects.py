from django.core.management.base import BaseCommand, CommandError
from app_center.research_assistant.backend.models import ResearchProject
from app_center.research_assistant.backend.services import cleanup_project


class Command(BaseCommand):
    help = "Retry storage cleanup for deleted research projects."

    def handle(self, *args, **options):
        failed = 0
        for project in ResearchProject.objects.filter(deleted_at__isnull=False, cleanup_pending=True):
            try:
                cleanup_project(project)
            except Exception:
                failed += 1
                self.stderr.write(f"Cleanup pending: {project.id}")
        if failed:
            raise CommandError(f"{failed} research projects still require cleanup.")

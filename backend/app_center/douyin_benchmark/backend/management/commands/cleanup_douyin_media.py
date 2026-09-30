import shutil
import time
from django.core.management.base import BaseCommand
from app_center.douyin_benchmark.backend.models import Task, Work
from app_center.douyin_benchmark.backend.media import root
from modules.tenancy.database import tenant_database_context
from apps.enterprise.models import Organization


class Command(BaseCommand):
    help = "Remove unreferenced Douyin private media older than 24 hours."

    def handle(self, **options):
        task_ids, uploads = set(), set()
        for org_id in Organization.objects.values_list("id", flat=True).iterator():
            with tenant_database_context(org_id):
                tasks = Task.objects.filter(organization_id=org_id)
                task_ids.update(str(pk) for pk in tasks.values_list("id", flat=True))
                keys = list(Work.objects.filter(account__organization_id=org_id).values_list("media_key", flat=True))
                keys += [value.get("media_key", "") for value in tasks.values_list("input", flat=True)]
                uploads.update(key.split("/")[1] for key in keys if key.startswith("uploads/") and len(key.split("/")) == 3)
        removed = 0
        for name, retained in (("tasks", task_ids), ("uploads", uploads)):
            folder = root() / name
            if not folder.exists():
                continue
            for directory in folder.iterdir():
                if directory.is_dir() and not directory.is_symlink() and directory.name not in retained and directory.stat().st_mtime < time.time() - 86400:
                    shutil.rmtree(directory)
                    removed += 1
        self.stdout.write(f"Removed {removed} orphan media directories.")

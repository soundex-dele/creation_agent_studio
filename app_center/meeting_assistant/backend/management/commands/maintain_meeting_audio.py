"""Reclaim orphaned private audio after uploads/deletions interrupted by a crash."""
import time
from django.core.management.base import BaseCommand
from apps.enterprise.models import Organization
from modules.tenancy.database import tenant_database_context
from ...models import Recording
from ...storage import object_path


class Command(BaseCommand):
    help = "清理一小时前遗留的无记录私有录音文件（不删除有效录音）。"

    def handle(self, *args, **options):
        root = object_path(".cleanup-marker").parent
        if not root.is_dir():
            return
        # Query within each tenant context so PostgreSQL RLS never hides live rows.
        active = set()
        for organization_id in Organization.objects.values_list("id", flat=True):
            with tenant_database_context(organization_id):
                active.update(Recording.objects.filter(organization_id=organization_id).values_list("object_key", flat=True))
        cutoff = time.time() - 3600
        count = 0
        for candidate in root.glob("*/*/*"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            key = candidate.relative_to(root).as_posix()
            path = object_path(key)
            if key not in active and path.stat().st_mtime < cutoff:
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    self.stderr.write(f"文件仍被占用，下次重试：{key}")
        self.stdout.write(f"已清理 {count} 个遗留录音文件。")

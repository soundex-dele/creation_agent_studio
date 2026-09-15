from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.applications.app_center.discovery import discover_packages


class Command(BaseCommand):
    help = "Show discovery and migration status for bundled application packages."

    def handle(self, *args, **options):
        packages, errors = discover_packages(settings.APP_CENTER_ROOT, strict=False)
        executor = MigrationExecutor(connection)
        applied = executor.loader.applied_migrations
        for package in packages:
            spec = package.manifest.spec
            app_label = "-"
            migration_state = "n/a"
            if spec.backend.django_app:
                module_name = spec.backend.django_app.rsplit(".", 1)[0]
                config = next((
                    item for item in apps.get_app_configs()
                    if item.module.__name__ == module_name.rsplit(".apps", 1)[0]
                ), None)
                if config is None:
                    migration_state = "appconfig-invalid"
                else:
                    app_label = config.label
                    leaves = executor.loader.graph.leaf_nodes(app_label)
                    migration_state = "applied" if all(node in applied for node in leaves) else "pending"
            self.stdout.write(
                f"{package.manifest.metadata.id}: valid; django_label={app_label}; "
                f"migrations={migration_state}; hash={package.content_hash[:12]}"
            )
        for error in errors:
            self.stderr.write(f"INVALID {error}")

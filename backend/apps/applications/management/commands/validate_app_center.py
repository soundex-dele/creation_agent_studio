from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.applications.app_center.discovery import AppCenterError, discover_packages


class Command(BaseCommand):
    help = "Validate all bundled application package manifests."

    def handle(self, *args, **options):
        try:
            packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
        except AppCenterError as exc:
            raise CommandError(str(exc)) from exc
        loaded_configs = {
            f"{config.__class__.__module__}.{config.__class__.__name__}"
            for config in apps.get_app_configs()
        }
        for package in packages:
            django_app = package.manifest.spec.backend.django_app
            if django_app and django_app not in loaded_configs:
                raise CommandError(
                    f"{package.manifest_path}: Django AppConfig {django_app!r} "
                    "cannot be imported"
                )
            database = package.manifest.spec.database
            self.stdout.write(
                f"OK {package.manifest.metadata.id} {package.manifest.metadata.version} "
                f"database={database.mode} hash={package.content_hash[:12]}"
            )
        self.stdout.write(self.style.SUCCESS(f"Validated {len(packages)} application package(s)."))

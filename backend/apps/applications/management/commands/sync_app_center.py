from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.applications.app_center.discovery import AppCenterError, discover_packages
from apps.applications.app_center.installer import sync_packages


class Command(BaseCommand):
    help = "Idempotently synchronize bundled application packages into the catalog."

    def add_arguments(self, parser):
        parser.add_argument("--package", dest="package_id")
        parser.add_argument("--organization", dest="organization_id")

    def handle(self, *args, **options):
        try:
            packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
        except AppCenterError as exc:
            raise CommandError(str(exc)) from exc
        if options["package_id"]:
            packages = [
                package for package in packages
                if package.manifest.metadata.id == options["package_id"]
            ]
            if not packages:
                raise CommandError(f"Unknown application package: {options['package_id']}")
        result = sync_packages(packages, organization_id=options["organization_id"])
        self.stdout.write(self.style.SUCCESS(
            "Application center synchronized: "
            f"applications_created={result.applications_created}, "
            f"drafts_changed={result.drafts_changed}, "
            f"revisions_created={result.revisions_created}, "
            f"deployments_changed={result.deployments_changed}."
        ))

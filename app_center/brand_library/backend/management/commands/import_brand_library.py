"""Import a portable brand bundle using the application's validation and scope."""

import json
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.applications.models import Application
from apps.enterprise.models import Organization
from modules.tenancy.database import tenant_database_context
from app_center.brand_library.backend.serializers import (
    ExampleSerializer, ProductSerializer, ProfileSerializer,
)
from app_center.brand_library.backend.views import available_applications


SERIALIZERS = {
    "profile": ProfileSerializer,
    "products": ProductSerializer,
    "examples": ExampleSerializer,
}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CommandError(f"Cannot read JSON {path}: {exc}") from exc


def load_bundle(path):
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise CommandError("Bundle must be an object with version: 1.")
    if set(manifest) - {"version", "profile", "products", "examples"}:
        raise CommandError("Unknown bundle fields.")
    entries = []
    for kind, serializer_class in SERIALIZERS.items():
        filenames = [manifest.get("profile")] if kind == "profile" else manifest.get(kind, [])
        if not isinstance(filenames, list):
            raise CommandError(f"{kind} must be a list of JSON filenames.")
        names = set()
        for filename in filenames:
            if not isinstance(filename, str) or not filename:
                raise CommandError(f"Missing or invalid {kind} filename.")
            source = (path.parent / filename).resolve()
            if not source.is_relative_to(path.parent.resolve()):
                raise CommandError(f"Bundle file must stay inside its directory: {filename}")
            data = read_json(source)
            serializer = serializer_class(data=data)
            writable = {key for key, field in serializer.fields.items() if not field.read_only}
            if not isinstance(data, dict) or set(data) - writable:
                raise CommandError(f"{filename}: unknown or server-owned fields; omit IDs and ownership.")
            if not serializer.is_valid():
                raise CommandError(f"{filename}: {serializer.errors}")
            name = serializer.validated_data["name"]
            if name in names:
                raise CommandError(f"Duplicate {kind} name in bundle: {name}")
            names.add(name)
            entries.append({"kind": kind, "source": filename, "serializer": serializer})
    return entries


def resolve_destination(username, organization):
    user = get_user_model().objects.filter(username=username, is_active=True).first()
    if user is None:
        raise CommandError(f"Active user not found: {username}")
    if getattr(user, "role", None) == "auditor":
        raise CommandError("Auditor accounts cannot import brand data.")
    # Require an actual membership; importing does not create users or grant access.
    organizations = Organization.objects.filter(
        is_active=True, memberships__user=user, memberships__is_active=True,
    ).distinct()
    if organization:
        try:
            organization_id = UUID(organization)
        except ValueError:
            organizations = organizations.filter(slug=organization)
        else:
            organizations = organizations.filter(pk=organization_id)
    matches = list(organizations)
    if len(matches) != 1:
        raise CommandError(
            "Select exactly one active organization membership with --organization UUID_OR_SLUG. "
            f"Matching organizations: {[{'id': str(org.pk), 'slug': org.slug} for org in matches]}"
        )
    org = matches[0]
    with tenant_database_context(org.pk):
        app = available_applications(org.pk, user).first()
    if app is None:
        raise CommandError(
            "No runnable brand-library application in this organization. "
            "Apply migrations and run sync_app_center --package brand-library "
            "--organization <UUID>, then check user access."
        )
    return user, org, app


class Command(BaseCommand):
    help = "Import a brand profile, products and examples atomically; identical entries are skipped."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Existing destination account (exact username).")
        parser.add_argument("--organization", help="Organization UUID or slug; required when membership is ambiguous.")
        parser.add_argument(
            "--bundle", type=Path,
            default=Path(settings.BASE_DIR).parent / "docs/brands/agentic-ai-workshop/import-manifest.json",
            help="Portable JSON bundle manifest; defaults to the 智能体AI工坊 bundle.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate and show the plan without writing data.")
        parser.add_argument(
            "--on-conflict", choices=("error", "update"), default="error",
            help="Different data under an existing name: stop (default) or update supplied fields.",
        )

    def handle(self, *args, **options):
        entries = load_bundle(options["bundle"].resolve())
        user, org, app = resolve_destination(options["username"], options["organization"])
        dry_run = options["dry_run"]
        with tenant_database_context(org.pk), transaction.atomic():
            # Serialize concurrent imports into this application where row locks are supported.
            if not dry_run:
                Application.objects.select_for_update().get(pk=app.pk)
            scope = {"owner": user, "organization": org, "application": app}
            profile = None
            conflicts = []
            for entry in entries:
                serializer = entry["serializer"]
                queryset = serializer.Meta.model.objects.filter(**scope)
                if entry["kind"] != "profile":
                    queryset = queryset.filter(profile=profile) if profile else queryset.none()
                matches = list(queryset.filter(name=serializer.validated_data["name"])[:2])
                if len(matches) > 1:
                    raise CommandError(f"Duplicate existing {entry['kind']} name; resolve before importing.")
                instance = matches[0] if matches else None
                changed = [
                    key for key, value in serializer.validated_data.items()
                    if instance is None or getattr(instance, key) != value
                ]
                action = "create" if instance is None else "update" if changed else "skip"
                entry.update(instance=instance, action=action, changed_fields=changed)
                if entry["kind"] == "profile":
                    profile = instance
                if action == "update" and options["on_conflict"] == "error":
                    conflicts.append(f"{entry['kind']}: {serializer.validated_data['name']} ({', '.join(changed)})")
            report = {
                "dry_run": dry_run, "username": user.username,
                "organization_id": str(org.pk), "organization_slug": org.slug,
                "application_id": app.pk, "conflicts": conflicts,
                "entries": [],
            }
            # Inspect every conflict before making any changes.
            if conflicts and not dry_run:
                raise CommandError("Existing data differs; nothing imported. Review --dry-run, then use "
                                   "--on-conflict update if intended: " + "; ".join(conflicts))
            for entry in entries:
                serializer = entry["serializer"]
                instance = entry["instance"]
                if not dry_run and entry["action"] != "skip":
                    serializer.instance = instance
                    extra = {} if entry["kind"] == "profile" else {"profile": profile}
                    instance = serializer.save(**scope, **extra)
                if entry["kind"] == "profile":
                    profile = instance
                if not dry_run:
                    instance.refresh_from_db()
                    if any(getattr(instance, key) != value for key, value in serializer.validated_data.items()):
                        raise CommandError(f"Read-back mismatch: {entry['source']}; transaction rolled back.")
                report["entries"].append({
                    "kind": entry["kind"], "name": serializer.validated_data["name"],
                    "action": entry["action"], "changed_fields": entry["changed_fields"],
                    "id": str(instance.pk) if instance else None,
                })
            if not dry_run and any(entry["action"] != "skip" for entry in entries):
                profile.save(update_fields=["updated_at"])
        report["status"] = "preview" if dry_run else "committed_and_verified"
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))

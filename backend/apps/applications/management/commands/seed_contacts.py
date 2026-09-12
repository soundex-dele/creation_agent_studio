"""Idempotently add a dedicated contacts application to each organization."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.applications.models import Application, ApplicationCategory
from apps.contacts.models import AddressBook
from apps.enterprise.models import Organization
from modules.catalog.models import ApplicationDraft
from modules.tenancy.database import tenant_database_context


SLUG = "contacts"
DEFINITION = {
    "kind": "custom",
    "executor_kind": "media",
    "executor_key": "contacts",
    "executor_protocol_version": 1,
    "renderer_key": "contacts",
    "renderer_schema_version": 1,
    "retry_policy": {"max_attempts": 1, "retry_safe": False},
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "default_config": {"launch_mode": "dedicated", "allow_export": False},
    "dependencies": {"agents": [], "skills": []},
}


class Command(BaseCommand):
    help = "Seed the organization-scoped contacts application and address book."

    def handle(self, *args, **options):
        category, _ = ApplicationCategory.objects.get_or_create(
            slug="office",
            defaults={
                "name": "办公效率",
                "description": "组织协作和办公工具",
                "icon": "💼",
                "order": 20,
            },
        )
        organizations = Organization.objects.filter(is_active=True).select_related("owner")
        if not organizations.exists():
            self.stderr.write("No active organization exists — register a user, then re-run.")
            return

        created_count = 0
        for organization in organizations:
            with transaction.atomic(), tenant_database_context(organization.id):
                application, created = Application.objects.update_or_create(
                    organization=organization,
                    slug=SLUG,
                    defaults={
                        "category": category,
                        "name": "通讯录",
                        "description": "集中管理组织联系人、公司信息和多种联系方式。",
                        "icon": "👥",
                        "color": "#2563eb",
                        "tags": ["联系人", "办公", "协作"],
                        "developer": "Creation Studio",
                        "is_public": True,
                        "is_active": True,
                        "kind": Application.Kind.CUSTOM,
                        "created_by": organization.owner,
                    },
                )
                draft, draft_created = ApplicationDraft.objects.get_or_create(
                    organization=organization,
                    application=application,
                    defaults={
                        "updated_by": organization.owner,
                        "content": DEFINITION,
                    },
                )
                if not draft_created and draft.content != DEFINITION:
                    draft.content = DEFINITION
                    draft.version += 1
                    draft.updated_by = organization.owner
                    draft.save(update_fields=[
                        "content", "version", "updated_by", "updated_at",
                    ])
                AddressBook.objects.update_or_create(
                    application=application,
                    defaults={"organization": organization, "name": "企业通讯录"},
                )
                created_count += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"Contacts application ready for {organizations.count()} organization(s); "
            f"created {created_count}."
        ))

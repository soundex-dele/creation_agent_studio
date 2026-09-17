from __future__ import annotations

import importlib
from copy import deepcopy
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from modules.catalog.definition import validate_application_definition
from modules.catalog.models import ApplicationDeployment, ApplicationDraft
from modules.catalog.services import publish_application, switch_application_deployment
from modules.tenancy.database import tenant_database_context

from apps.applications.models import Application, ApplicationCategory, ChatApplication
from apps.enterprise.models import Organization

from .discovery import DiscoveredPackage, discover_packages


@dataclass
class SyncResult:
    applications_created: int = 0
    drafts_changed: int = 0
    revisions_created: int = 0
    deployments_changed: int = 0

    def add(self, other: "SyncResult") -> None:
        self.applications_created += other.applications_created
        self.drafts_changed += other.drafts_changed
        self.revisions_created += other.revisions_created
        self.deployments_changed += other.deployments_changed


def _load_callable(dotted_path: str):
    module_name, attribute = dotted_path.rsplit(".", 1)
    callback = getattr(importlib.import_module(module_name), attribute)
    if not callable(callback):
        raise TypeError(f"{dotted_path} is not callable")
    return callback


def sync_package(package: DiscoveredPackage, organization: Organization) -> SyncResult:
    manifest = package.manifest
    metadata = manifest.metadata
    spec = manifest.spec
    result = SyncResult()

    category, _ = ApplicationCategory.objects.update_or_create(
        slug=metadata.category.slug,
        defaults={
            "name": metadata.category.name,
            "description": metadata.category.description,
            "icon": metadata.category.icon,
            "order": metadata.category.order,
        },
    )

    with transaction.atomic(), tenant_database_context(organization.id):
        application, created = Application.objects.update_or_create(
            organization=organization,
            slug=metadata.id,
            defaults={
                "category": category,
                "name": metadata.name,
                "description": metadata.description,
                "icon": metadata.icon,
                "color": metadata.color,
                "tags": metadata.tags,
                "developer": metadata.developer,
                "is_public": True,
                "is_active": True,
                "kind": spec.application_kind,
                "created_by": organization.owner,
            },
        )
        result.applications_created = int(created)
        if spec.application_kind == Application.Kind.CHAT:
            ChatApplication.objects.get_or_create(application=application)

        definition = deepcopy(spec.definition)
        if spec.backend.definition_factory:
            definition = _load_callable(spec.backend.definition_factory)(
                organization=organization,
                application=application,
                definition=definition,
            )
            validate_application_definition(definition)

        draft, draft_created = ApplicationDraft.objects.get_or_create(
            organization=organization,
            application=application,
            defaults={"updated_by": organization.owner, "content": definition},
        )
        if draft_created:
            result.drafts_changed = 1
        elif draft.content != definition:
            draft.content = definition
            draft.version += 1
            draft.updated_by = organization.owner
            draft.save(update_fields=["content", "version", "updated_by", "updated_at"])
            result.drafts_changed = 1

        revision_count = application.revisions.count()
        revision = publish_application(
            application=application,
            actor=organization.owner,
            expected_draft_version=draft.version,
            release_notes=f"app_center {metadata.id} {metadata.version} ({package.content_hash[:12]})",
        )
        result.revisions_created = int(application.revisions.count() > revision_count)

        if spec.install.activate:
            deployment = ApplicationDeployment.objects.filter(
                application=application
            ).first()
            if deployment is None or deployment.revision_id != revision.id:
                switch_application_deployment(
                    application=application,
                    actor=organization.owner,
                    revision_id=revision.id,
                    expected_version=deployment.version if deployment else 0,
                )
                result.deployments_changed = 1

        if spec.backend.install_hook:
            _load_callable(spec.backend.install_hook)(
                organization=organization,
                application=application,
            )
    return result


def sync_packages(packages: list[DiscoveredPackage], *, organization_id=None) -> SyncResult:
    organizations = Organization.objects.filter(is_active=True).select_related("owner")
    if organization_id:
        organizations = organizations.filter(pk=organization_id)
    total = SyncResult()
    for organization in organizations:
        for package in packages:
            total.add(sync_package(package, organization))
    return total


def install_for_organization(organization: Organization) -> SyncResult:
    """Install every valid per-organization package for a newly created tenant."""

    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
    total = SyncResult()
    for package in packages:
        total.add(sync_package(package, organization))
    return total

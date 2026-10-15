"""Permission-checked brand references shared with other bundled applications."""
from modules.platform_api.identity import Application, accessible_resources
from .backend.models import BrandProfile


def available_applications(organization_id, user):
    return accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug="brand-library", kind=Application.Kind.CUSTOM, is_active=True,
    ), user, operation="run")


def private_profiles(organization_id, user):
    return BrandProfile.objects.for_organization(organization_id).filter(
        owner=user, application__in=available_applications(organization_id, user),
    )

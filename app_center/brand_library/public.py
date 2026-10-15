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


_EXPORTS = {'BrandReferenceSerializer': 'app_center.brand_library.backend.serializers',
 'resolve_brand_snapshot': 'app_center.brand_library.backend.context'}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(_EXPORTS[name]), name)

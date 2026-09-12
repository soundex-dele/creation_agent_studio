from django.core.exceptions import ValidationError
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Membership, Organization
from .tenancy import provision_single_tenant_user, single_tenant_mode_enabled


ROLE_LEVEL = {
    Membership.Role.VIEWER: 10,
    Membership.Role.AUDITOR: 20,
    Membership.Role.OPERATOR: 30,
    Membership.Role.DEVELOPER: 40,
    Membership.Role.ADMIN: 50,
    Membership.Role.OWNER: 60,
}


def resolve_organization(request, *, required=True):
    """Resolve a tenant only through an active membership."""
    if not request.user or not request.user.is_authenticated:
        return None
    if single_tenant_mode_enabled():
        membership = provision_single_tenant_user(request.user)
        if membership:
            request.organization = membership.organization
            request.organization_membership = membership
            return membership.organization
        return None

    requested = request.headers.get('X-Organization-ID') or request.query_params.get(
        'organization_id')
    memberships = Membership.objects.select_related('organization').filter(
        user=request.user, is_active=True, organization__is_active=True)
    if requested:
        try:
            membership = memberships.filter(organization_id=requested).first()
        except (ValidationError, ValueError):
            membership = None
    else:
        membership = memberships.order_by('created_at').first()
    if membership:
        request.organization = membership.organization
        request.organization_membership = membership
        return membership.organization
    if required:
        return None
    return None


class HasOrganization(BasePermission):
    def has_permission(self, request, view):
        return resolve_organization(request) is not None


class OrganizationRolePermission(BasePermission):
    """Viewer for reads; developer for writes; admin for member/policy writes."""

    def has_permission(self, request, view):
        organization = resolve_organization(request)
        if organization is None:
            return False
        role = request.organization_membership.role
        required = getattr(view, 'minimum_role', None)
        if required is None:
            required = (Membership.Role.VIEWER if request.method in SAFE_METHODS
                        else getattr(view, 'minimum_write_role', Membership.Role.DEVELOPER))
        return ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL.get(required, 100)


class IsOrganizationMember(BasePermission):
    def has_object_permission(self, request, view, obj):
        organization = obj if isinstance(obj, Organization) else getattr(
            obj, 'organization', None)
        return bool(organization and Membership.objects.filter(
            organization=organization, user=request.user, is_active=True).exists())

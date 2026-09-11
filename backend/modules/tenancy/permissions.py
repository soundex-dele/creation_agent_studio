from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Membership, Organization


ROLE_LEVEL = {
    Membership.Role.VIEWER: 10,
    Membership.Role.AUDITOR: 20,
    Membership.Role.OPERATOR: 30,
    Membership.Role.DEVELOPER: 40,
    Membership.Role.ADMIN: 50,
    Membership.Role.OWNER: 60,
}


def resolve_path_organization(request, organization_id):
    """Resolve a V2 organization without revealing inaccessible tenants."""

    if not request.user or not request.user.is_authenticated:
        return None
    organization = (
        Organization.objects.visible_to(request.user)
        .filter(pk=organization_id, is_active=True)
        .first()
    )
    if organization is not None:
        request.organization = organization
    return organization


class HasPathOrganization(BasePermission):
    """Require active access to the organization encoded in the V2 URL."""

    def has_permission(self, request, view):
        organization_id = view.kwargs.get("organization_id")
        return resolve_path_organization(request, organization_id) is not None


class HasPathOrganizationRole(BasePermission):
    """Resolve the path tenant and apply a per-view minimum role."""

    def has_permission(self, request, view):
        organization_id = view.kwargs.get("organization_id")
        organization = resolve_path_organization(request, organization_id)
        if organization is None:
            return False
        if request.user.is_superuser:
            return True
        membership = Membership.objects.filter(
            organization=organization,
            user=request.user,
            is_active=True,
        ).first()
        if membership is None:
            return False
        request.organization_membership = membership
        required = getattr(view, "minimum_role", None)
        if required is None:
            required = (
                Membership.Role.VIEWER
                if request.method in SAFE_METHODS
                else Membership.Role.DEVELOPER
            )
        return ROLE_LEVEL.get(membership.role, 0) >= ROLE_LEVEL.get(required, 100)

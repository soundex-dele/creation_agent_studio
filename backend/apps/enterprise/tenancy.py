"""Single-tenant deployment helpers.

Organization remains the canonical data, policy and audit boundary in every
deployment. In single-tenant mode the boundary is selected by the server and
is never selected by an untrusted client.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from .models import GovernancePolicy, Membership, Organization, QuotaPolicy


def single_tenant_mode_enabled():
    return bool(getattr(settings, 'SINGLE_TENANT_MODE', False))


def _configured_organization_id():
    value = str(getattr(settings, 'SINGLE_TENANT_ORGANIZATION_ID', '') or '').strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ImproperlyConfigured(
            'SINGLE_TENANT_ORGANIZATION_ID must be a valid UUID.') from exc


def _configured_slug():
    value = str(getattr(
        settings, 'SINGLE_TENANT_ORGANIZATION_SLUG', 'enterprise') or '')
    slug = slugify(value)[:100]
    if not slug:
        raise ImproperlyConfigured(
            'SINGLE_TENANT_ORGANIZATION_SLUG must contain a valid slug.')
    return slug


def get_single_tenant_organization(*, active_only=True):
    """Return the server-selected organization without creating it."""

    if not single_tenant_mode_enabled():
        return None
    organization_id = _configured_organization_id()
    queryset = Organization.objects.all()
    if active_only:
        queryset = queryset.filter(is_active=True)
    if organization_id is not None:
        return queryset.filter(pk=organization_id).first()
    return queryset.filter(slug=_configured_slug()).first()


def _default_member_role(user):
    if user.is_superuser:
        return Membership.Role.ADMIN
    role = str(getattr(
        settings, 'SINGLE_TENANT_DEFAULT_ROLE', Membership.Role.VIEWER) or '')
    allowed = dict(Membership.Role.choices)
    if role not in allowed or role == Membership.Role.OWNER:
        return Membership.Role.VIEWER
    return role


def _get_bootstrap_organization_for_update():
    """Return the organization created for the migration-only system user.

    Seed migrations need an owner before a real user has registered, so a
    fresh database contains a ``system`` user and its personal workspace.
    Reusing that workspace keeps the seeded agents and applications inside
    the single tenant instead of stranding them in a hidden organization.
    """

    if _configured_organization_id() is not None:
        return None
    return Organization.objects.select_for_update().filter(
        owner__username='system',
        owner__is_superuser=False,
        slug__startswith='system-',
        name='system Workspace',
    ).order_by('created_at').first()


@transaction.atomic
def provision_single_tenant_user(user):
    """Create the singleton organization if necessary and enroll ``user``.

    The first user owns the installation. Later users receive the configured
    default role; existing memberships retain their explicitly assigned role.
    """

    if not single_tenant_mode_enabled() or not user or not user.is_authenticated:
        return None

    organization = get_single_tenant_organization(active_only=False)
    first_owner = organization is None
    if first_owner:
        organization_id = _configured_organization_id()
        name = str(getattr(
            settings, 'SINGLE_TENANT_ORGANIZATION_NAME',
            'Enterprise Workspace') or '').strip() or 'Enterprise Workspace'
        bootstrap_organization = _get_bootstrap_organization_for_update()
        if bootstrap_organization is not None:
            organization = bootstrap_organization
            organization.name = name[:160]
            organization.slug = _configured_slug()
            organization.owner = user
            organization.is_active = True
            organization.save(update_fields=[
                'name', 'slug', 'owner', 'is_active', 'updated_at'])
        else:
            try:
                # The savepoint lets a concurrent first-login winner commit while
                # this transaction safely recovers from the unique slug/ID race.
                with transaction.atomic():
                    organization = Organization.objects.create(
                        **({'id': organization_id} if organization_id is not None else {}),
                        name=name[:160],
                        slug=_configured_slug(),
                        owner=user,
                        is_active=True,
                    )
            except IntegrityError:
                organization = get_single_tenant_organization(active_only=False)
                if organization is None:
                    raise ImproperlyConfigured(
                        'The configured single-tenant organization conflicts with '
                        'an existing organization ID or slug.')
                first_owner = False
    elif not organization.is_active:
        raise ImproperlyConfigured(
            'The configured single-tenant organization is inactive.')

    membership, membership_created = Membership.objects.get_or_create(
        organization=organization,
        user=user,
        defaults={
            'role': Membership.Role.OWNER if first_owner else _default_member_role(user),
            'is_active': True,
        },
    )
    # An inactive membership is an explicit administrator/SCIM revocation and
    # must not be undone by a later authenticated request.
    if not membership_created and not membership.is_active:
        return None

    QuotaPolicy.objects.get_or_create(organization=organization)
    GovernancePolicy.objects.get_or_create(organization=organization)
    return membership

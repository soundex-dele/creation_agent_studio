import uuid

from django.conf import settings
from django.db import models


class OrganizationQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_superuser:
            return self
        return self.filter(
            memberships__user=user,
            memberships__is_active=True,
        ).distinct()


class Organization(models.Model):
    """A hard tenant boundary for every V2 business resource."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=100, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="v2_owned_organizations",
    )
    is_active = models.BooleanField(default=True)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationQuerySet.as_manager()

    class Meta:
        db_table = "v2_organizations"
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Administrator"
        DEVELOPER = "developer", "Developer"
        OPERATOR = "operator", "Operator"
        AUDITOR = "auditor", "Auditor"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="v2_organization_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "v2_organization_memberships"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="v2_unique_organization_membership",
            )
        ]


class TenantOwnedQuerySet(models.QuerySet):
    def for_organization(self, organization_id):
        if organization_id is None:
            return self.none()
        return self.filter(organization_id=organization_id)


class TenantOwnedModel(models.Model):
    """Base model whose default manager exposes an explicit tenant scope."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="+",
    )

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        abstract = True

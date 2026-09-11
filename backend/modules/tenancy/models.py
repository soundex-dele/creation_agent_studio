"""Shared tenant primitives.

There is deliberately no second Organization model in the execution stack.
The enterprise control-plane Organization and Membership are the canonical
tenant identity for every product and durable-execution resource.
"""
from django.db import models

from apps.enterprise.models import Membership, Organization


class TenantOwnedQuerySet(models.QuerySet):
    def for_organization(self, organization_id):
        if organization_id is None:
            return self.none()
        return self.filter(organization_id=organization_id)


class TenantOwnedModel(models.Model):
    """Base model with an explicit canonical organization scope."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="+",
    )

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        abstract = True


__all__ = [
    "Membership",
    "Organization",
    "TenantOwnedModel",
    "TenantOwnedQuerySet",
]

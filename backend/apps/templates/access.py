"""One visibility boundary for the library and consumers of its references."""
from django.db.models import Q

from .models import Template


def visible_cases(user, organization_id):
    private_scope = Q(organization_id=organization_id) | Q(organization__isnull=True)
    return Template.objects.filter(
        Q(status='published') | (Q(created_by=user) & private_scope))

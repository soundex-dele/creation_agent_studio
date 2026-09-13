import re
import uuid

from django.conf import settings
from django.db import connection, transaction

from .database import set_local_organization


ORGANIZATION_PATH = re.compile(
    r"^/api/v1/organizations/(?P<organization_id>[0-9a-fA-F-]{36})(?:/|$)"
)


class TenantDatabaseContextMiddleware:
    """Scope every tenant-aware PostgreSQL transaction for row-level security."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if connection.vendor != "postgresql":
            return self.get_response(request)
        if getattr(settings, 'SINGLE_TENANT_MODE', False):
            # Import lazily so app loading is complete before model access.
            from apps.enterprise.tenancy import get_single_tenant_organization
            organization = get_single_tenant_organization()
            organization_id = organization.id if organization is not None else None
        else:
            match = ORGANIZATION_PATH.match(request.path)
            organization_id = (
                match.group("organization_id") if match is not None
                else request.headers.get("X-Organization-ID")
            )
        try:
            organization_id = uuid.UUID(str(organization_id))
        except (TypeError, ValueError):
            organization_id = None
        if organization_id is None:
            return self.get_response(request)
        with transaction.atomic():
            set_local_organization(organization_id)
            return self.get_response(request)

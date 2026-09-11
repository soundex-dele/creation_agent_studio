import re
import uuid

from django.db import connection, transaction

from .database import set_local_organization


ORGANIZATION_PATH = re.compile(
    r"^/api/organizations/(?P<organization_id>[0-9a-fA-F-]{36})(?:/|$)"
)


class TenantDatabaseContextMiddleware:
    """Scope every tenant-aware PostgreSQL transaction for row-level security."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = ORGANIZATION_PATH.match(request.path)
        organization_id = (
            match.group("organization_id") if match is not None
            else request.headers.get("X-Organization-ID")
        )
        try:
            organization_id = uuid.UUID(str(organization_id))
        except (TypeError, ValueError):
            organization_id = None
        if organization_id is None or connection.vendor != "postgresql":
            return self.get_response(request)
        with transaction.atomic():
            set_local_organization(organization_id)
            return self.get_response(request)

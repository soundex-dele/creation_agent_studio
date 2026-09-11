import re

from django.db import connection, transaction

from .database import set_local_organization


V2_ORGANIZATION_PATH = re.compile(
    r"^/api/v2/organizations/(?P<organization_id>[0-9a-fA-F-]{36})(?:/|$)"
)


class TenantDatabaseContextMiddleware:
    """Scope every PostgreSQL V2 API transaction for row-level security."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = V2_ORGANIZATION_PATH.match(request.path)
        if match is None or connection.vendor != "postgresql":
            return self.get_response(request)
        with transaction.atomic():
            set_local_organization(match.group("organization_id"))
            return self.get_response(request)

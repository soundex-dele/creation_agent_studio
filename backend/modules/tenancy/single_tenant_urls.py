"""Organization-free aliases for private single-tenant deployments."""
from functools import wraps

from django.http import JsonResponse
from django.urls import path

from apps.enterprise.tenancy import (
    get_single_tenant_organization,
    single_tenant_mode_enabled,
)
from modules.catalog.api.urls import urlpatterns as catalog_patterns
from modules.execution.api.urls import urlpatterns as execution_patterns


def _single_tenant_view(callback):
    @wraps(callback)
    def bound(request, *args, **kwargs):
        if not single_tenant_mode_enabled():
            return JsonResponse({'detail': 'Not found.'}, status=404)
        organization = get_single_tenant_organization()
        if organization is None:
            return JsonResponse({
                'detail': (
                    'The single-tenant organization has not been provisioned. '
                    'Load /api/enterprise/deployment-context/ after signing in.'
                ),
            }, status=503)
        return callback(
            request, *args, organization_id=organization.id, **kwargs)

    return bound


urlpatterns = [
    path(
        str(pattern.pattern),
        _single_tenant_view(pattern.callback),
        name=f'single-tenant-{index}-{pattern.name}',
    )
    for index, pattern in enumerate([*catalog_patterns, *execution_patterns])
]

"""
URL configuration for Creation Agent Studio backend.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from core.health import health, readiness

# Debug Toolbar URLs - must be first in urlpatterns
if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
else:
    urlpatterns = []

schema_view = get_schema_view(
    openapi.Info(
        title="Creation Agent Studio API",
        default_version='v1',
        description="API for Creation Agent Studio - AI-powered video creation platform",
        terms_of_service="https://www.example.com/terms/",
        contact=openapi.Contact(email="contact@example.com"),
        license=openapi.License(name="MIT License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns += [
    path('healthz/', health, name='health'),
    path('readyz/', readiness, name='readiness'),
    # Admin interface
    path('admin/', admin.site.urls),

    # API documentation
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('swagger.json', schema_view.without_ui(cache_timeout=0), name='schema-json'),

    # Stable public contract. The project is pre-launch, so every application
    # route uses one versioned surface instead of carrying compatibility aliases.
    path('api/v1/auth/', include('apps.users.urls')),
    path('api/v1/agents/', include('apps.agents.urls')),
    path('api/v1/apps/', include('apps.applications.urls')),
    path('api/v1/templates/', include('apps.templates.urls')),
    path('api/v1/conversations/', include('apps.conversations.urls')),
    path('api/v1/projects/', include('apps.projects.urls')),
    path('api/v1/marketplace/', include('apps.marketplace.urls')),
    path('api/v1/enterprise/', include('apps.enterprise.urls')),
    path('api/v1/workflows/', include('apps.workflows.urls')),
    path('api/v1/', include('modules.tenancy.single_tenant_urls')),
    path(
        'api/v1/organizations/<uuid:organization_id>/',
        include('modules.catalog.api.urls', namespace='catalog-v1'),
    ),
    path(
        'api/v1/organizations/<uuid:organization_id>/',
        include('modules.execution.api.urls', namespace='execution-v1'),
    ),
    path(
        'api/v1/organizations/<uuid:organization_id>/',
        include('apps.contacts.urls'),
    ),

]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

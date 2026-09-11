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

    # REST API authentication (using custom views)
    path('api/auth/', include('apps.users.urls')),

    # API endpoints for each app
    path('api/agents/', include('apps.agents.urls')),
    path('api/apps/', include('apps.applications.urls')),
    path('api/templates/', include('apps.templates.urls')),
    path('api/conversations/', include('apps.conversations.urls')),
    path('api/projects/', include('apps.projects.urls')),
    path('api/marketplace/', include('apps.marketplace.urls')),
    path('api/enterprise/', include('apps.enterprise.urls')),
    path('api/workflows/', include('apps.workflows.urls')),

    # Versioned definitions and durable Runs share the canonical organization.
    path(
        'api/organizations/<uuid:organization_id>/',
        include('modules.catalog.api.urls'),
    ),
    path(
        'api/organizations/<uuid:organization_id>/',
        include('modules.execution.api.urls'),
    ),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

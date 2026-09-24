"""Exercise drawing and canonical execution routes without unrelated app packages."""
from django.urls import include, path

urlpatterns = [
    path("api/v1/organizations/<uuid:organization_id>/", include("app_center.ai_drawing.backend.urls")),
    path("api/v1/organizations/<uuid:organization_id>/", include("modules.execution.api.urls", namespace="execution-v1")),
]

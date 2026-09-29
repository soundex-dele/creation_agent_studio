from django.urls import include, path

urlpatterns = [
    path("api/v1/organizations/<uuid:organization_id>/", include("app_center.animation_studio.backend.urls")),
    path("api/v1/organizations/<uuid:organization_id>/", include("modules.execution.api.urls", namespace="execution-v1")),
]

from django.urls import include, path

urlpatterns = [
    path("api/v1/organizations/<uuid:organization_id>/", include("app_center.research_assistant.backend.urls")),
    path("api/v1/organizations/<uuid:organization_id>/", include("apps.knowledge.urls")),
    path("api/v1/organizations/<uuid:organization_id>/", include("app_center.documents.backend.urls")),
    path("api/v1/organizations/<uuid:organization_id>/", include("app_center.my_drive.backend.urls")),
    path("api/v1/organizations/<uuid:organization_id>/", include("modules.execution.api.urls", namespace="execution-v1")),
]

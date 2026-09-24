"""Exercise the real views without importing unrelated in-progress app packages."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from apps.applications.views import ApplicationViewSet

router = DefaultRouter()
router.register("apps", ApplicationViewSet, basename="brand-test-apps")
urlpatterns = [
    path("api/v1/organizations/<uuid:organization_id>/", include("app_center.brand_library.backend.urls")),
    path("api/v1/", include(router.urls)),
]

from rest_framework.routers import DefaultRouter

from .views import WorkflowViewSet


router = DefaultRouter()
router.register('', WorkflowViewSet, basename='workflow')

urlpatterns = router.urls

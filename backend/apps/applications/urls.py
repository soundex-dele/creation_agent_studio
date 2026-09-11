from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ApplicationCategoryViewSet,
    ApplicationViewSet,
    SkillViewSet,
)
from .runtime_files import list_runtime_directories, scan_runtime_folder

router = DefaultRouter()
router.register(r'categories', ApplicationCategoryViewSet, basename='application_category')
router.register(r'skills', SkillViewSet, basename='skill')
router.register(r'', ApplicationViewSet, basename='application')

urlpatterns = [
    # Explicit path BEFORE the router include so it wins over /apps/<slug>/.
    path('runtime-files/list/', list_runtime_directories,
         name='runtime-file-directory-list'),
    path('runtime-files/scan/', scan_runtime_folder,
         name='runtime-file-scan'),
    path('', include(router.urls)),
]

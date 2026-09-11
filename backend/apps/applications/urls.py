from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ApplicationCategoryViewSet,
    ApplicationViewSet,
    SkillViewSet,
    generate_image,
)
from .runtime_skill_views import (
    RuntimeSkillCollectionView,
    RuntimeSkillDetailView,
)
from .runtime_files import list_runtime_directories, scan_runtime_folder

router = DefaultRouter()
router.register(r'categories', ApplicationCategoryViewSet, basename='application_category')
router.register(r'skills', SkillViewSet, basename='skill')
router.register(r'', ApplicationViewSet, basename='application')

urlpatterns = [
    # Explicit path BEFORE the router include so it wins over /apps/<slug>/.
    path('image-generate/', generate_image),
    path('runtime-files/list/', list_runtime_directories,
         name='runtime-file-directory-list'),
    path('runtime-files/scan/', scan_runtime_folder,
         name='runtime-file-scan'),
    path('runtime-skills/', RuntimeSkillCollectionView.as_view(),
         name='runtime-skill-list'),
    path('runtime-skills/<str:provider>/<str:slug>/',
         RuntimeSkillDetailView.as_view(), name='runtime-skill-detail'),
    path('', include(router.urls)),
]

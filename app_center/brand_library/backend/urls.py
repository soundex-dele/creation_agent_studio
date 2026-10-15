from django.urls import path
from . import views

root = "applications/<int:application_id>/brand-library/profiles"
urlpatterns = [
    path("brand-library/profiles", views.ProfileChoices.as_view()),
    path(root, views.ProfileList.as_view()),
    path(root + "/<uuid:pk>", views.ProfileDetail.as_view()),
    path(root + "/<uuid:profile_id>/products", views.ProductList.as_view()),
    path(root + "/<uuid:profile_id>/products/<uuid:pk>", views.ProductDetail.as_view()),
    path(root + "/<uuid:profile_id>/examples", views.ExampleList.as_view()),
    path(root + "/<uuid:profile_id>/examples/<uuid:pk>", views.ExampleDetail.as_view()),
]

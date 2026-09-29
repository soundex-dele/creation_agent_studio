from django.urls import path
from . import views

prefix = "applications/<int:application_id>/animation-studio/"
urlpatterns = [
    path(prefix + "assets", views.AssetsView.as_view()),
    path(prefix + "generations", views.GenerationsView.as_view()),
    path(prefix + "generations/<uuid:run_id>", views.GenerationView.as_view()),
    path(prefix + "generations/<uuid:run_id>/exports", views.ExportsView.as_view()),
]

from django.urls import path
from . import views

prefix = "applications/<int:application_id>/ai-drawing/"
urlpatterns = [
    path(prefix + "references", views.ReferencesView.as_view()),
    path(prefix + "references/<uuid:reference_id>/content", views.ReferenceContentView.as_view()),
    path(prefix + "generations", views.GenerationsView.as_view()),
    path(prefix + "generations/<uuid:run_id>", views.GenerationView.as_view()),
]

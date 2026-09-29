from django.urls import path
from . import views, studio_views, batch

prefix = "applications/<int:application_id>/animation-studio/"
urlpatterns = [
    path(prefix + "batches/import", batch.BatchImportView.as_view()),
    path(prefix + "batches", batch.BatchesView.as_view()),
    path(prefix + "batches/<uuid:batch_id>", batch.BatchView.as_view()),
    path(prefix + "projects", studio_views.ProjectsView.as_view()),
    path(prefix + "projects/<uuid:project_id>", studio_views.ProjectView.as_view()),
    path(prefix + "projects/<uuid:project_id>/draft", studio_views.DraftView.as_view()),
    path(prefix + "projects/<uuid:project_id>/tasks", studio_views.ProjectTasksView.as_view()),
    path(prefix + "projects/<uuid:project_id>/<str:operation>", studio_views.ProjectActionView.as_view()),
    path(prefix + "presets", studio_views.PresetsView.as_view()),
    path(prefix + "speech-config", studio_views.SpeechConfigView.as_view()),
    path(prefix + "assets/<uuid:asset_id>", studio_views.AssetView.as_view()),
    path(prefix + "assets", views.AssetsView.as_view()),
    path(prefix + "generations", views.GenerationsView.as_view()),
    path(prefix + "generations/<uuid:run_id>", views.GenerationView.as_view()),
    path(prefix + "generations/<uuid:run_id>/exports", views.ExportsView.as_view()),
]

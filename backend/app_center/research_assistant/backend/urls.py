from django.urls import path
from . import views

root = "applications/<int:application_id>/research-assistant"
project = root + "/projects/<uuid:project_id>"
result = project + "/results/<uuid:result_id>"
urlpatterns = [
    path(root + "/integrations", views.IntegrationsView.as_view()),
    path(root + "/imports", views.ImportsView.as_view()),
    path(root + "/projects", views.ProjectsView.as_view()),
    path(project, views.ProjectView.as_view()),
    path(project + "/sources", views.SourcesView.as_view()),
    path(project + "/sources/<uuid:source_id>", views.SourceView.as_view()),
    path(project + "/sources/<uuid:source_id>/retry", views.SourceRetryView.as_view()),
    path(project + "/sources/<uuid:source_id>/content", views.SourceContentView.as_view()),
    path(project + "/results", views.ResultsView.as_view()),
    path(result, views.ResultView.as_view()),
    path(result + "/cancel", views.ResultCancelView.as_view()),
    path(result + "/citations/<str:citation_id>", views.CitationView.as_view()),
    path(result + "/download", views.ResultDownloadView.as_view()),
    path(result + "/export", views.ResultExportView.as_view()),
]

from django.urls import path
from . import views

root = 'applications/<int:application_id>/repo-explainer'
project = root + '/projects/<uuid:project_id>'
urlpatterns = [
    path(root + '/projects', views.ProjectsView.as_view()),
    path(root + '/integrations', views.IntegrationsView.as_view()),
    path(root + '/handoffs/<uuid:handoff_id>', views.HandoffView.as_view()),
    path(project, views.ProjectView.as_view()),
    path(project + '/imports', views.ImportView.as_view()),
    path(project + '/tasks', views.TasksView.as_view()),
    path(project + '/tasks/<uuid:task_id>', views.TaskView.as_view()),
    path(project + '/tasks/<uuid:task_id>/cancel', views.TaskView.as_view()),
    path(project + '/snapshots/<uuid:snapshot_id>/evidence', views.EvidenceView.as_view()),
    path(project + '/contents/<uuid:content_id>', views.ContentView.as_view()),
    path(project + '/contents/<uuid:content_id>/download', views.DownloadView.as_view()),
    path(project + '/handoffs', views.HandoffsView.as_view()),
]

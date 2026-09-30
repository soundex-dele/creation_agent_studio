from django.urls import path
from . import views

root = "applications/<int:application_id>/douyin-benchmark"
account = root + "/accounts/<uuid:account_id>"
task = account + "/tasks/<uuid:task_id>"
urlpatterns = [
    path(root + "/animation-integrations", views.AnimationIntegrationsView.as_view()),
    path(root + "/collector-config", views.CollectorConfigView.as_view()),
    path(root + "/connection", views.ConnectionView.as_view()),
    path(root + "/brands", views.BrandsView.as_view()),
    path(root + "/accounts", views.AccountsView.as_view()),
    path(account, views.AccountView.as_view()),
    path(account + "/works", views.WorksView.as_view()),
    path(account + "/works/<uuid:work_id>/upload", views.UploadView.as_view()),
    path(account + "/tasks", views.TasksView.as_view()),
    path(task, views.TaskView.as_view()),
    path(task + "/cancel", views.CancelView.as_view()),
    path(task + "/frames/<str:frame_id>", views.FrameView.as_view()),
    path(task + "/versions", views.VersionsView.as_view()),
    path(task + "/versions/<uuid:version_id>/download", views.DownloadView.as_view()),
]

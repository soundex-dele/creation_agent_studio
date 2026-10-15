from django.urls import path
from . import views

root = "applications/<int:application_id>/disk-cleaner"
urlpatterns = [
    path(root + "/host", views.HostView.as_view()),
    path(root + "/directories", views.DirectoryView.as_view()),
    path(root + "/tasks", views.TaskList.as_view()),
    path(root + "/tasks/<uuid:pk>", views.TaskDetail.as_view()),
    path(root + "/tasks/<uuid:pk>/entries", views.EntryList.as_view()),
    path(root + "/previews", views.PreviewList.as_view()),
    path(root + "/previews/<uuid:pk>", views.PreviewDetail.as_view()),
    path(root + "/cleanups", views.CleanupList.as_view()),
]

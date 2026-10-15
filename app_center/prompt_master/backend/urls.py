from django.urls import path
from .views import CatalogView, SessionsView, SessionView, CopyView, VersionsView, TasksView, TaskView, CancelView

prefix = "applications/<int:application_id>/prompt-master/"
session = prefix + "sessions/<uuid:session_id>"
urlpatterns = [
    path(prefix + "catalog", CatalogView.as_view()),
    path(prefix + "sessions", SessionsView.as_view()),
    path(session, SessionView.as_view()),
    path(session + "/copy", CopyView.as_view()),
    path(session + "/versions", VersionsView.as_view()),
    path(session + "/tasks", TasksView.as_view()),
    path(session + "/tasks/<uuid:task_id>", TaskView.as_view()),
    path(session + "/tasks/<uuid:task_id>/cancel", CancelView.as_view()),
]

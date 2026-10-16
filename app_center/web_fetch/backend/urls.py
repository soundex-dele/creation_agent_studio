from django.urls import path
from .views import RunsView, RunView

prefix = "applications/<int:application_id>/web-fetch/"
urlpatterns = [
    path(prefix + "runs", RunsView.as_view()),
    path(prefix + "runs/<uuid:run_id>", RunView.as_view()),
]

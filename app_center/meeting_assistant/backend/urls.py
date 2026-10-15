from django.urls import path
from . import views, media

root = "applications/<int:application_id>/meeting-assistant"
record = root + "/records/<uuid:pk>"
urlpatterns = [
    path(root + "/records", views.RecordList.as_view()),
    path(record, views.RecordDetail.as_view()),
    path(record + "/transcript", views.Transcript.as_view()),
    path(record + "/runs", views.RecordRuns.as_view()),
    path(record + "/cancel", views.CancelRun.as_view()),
    path(record + "/access", media.AudioAccess.as_view()),
    path(root + "/content", media.AudioContent.as_view()),
    path(record + "/actions/<uuid:action_id>", views.ActionDetail.as_view()),
    path(record + "/confirm-actions", views.ConfirmActions.as_view()),
    path(record + "/documents", views.ExportDocument.as_view()),
]

from django.urls import path
from . import views

root = "applications/<int:application_id>/documents"
urlpatterns = [
    path(root, views.DocumentList.as_view()),
    path(root + "/members", views.DocumentMembers.as_view()),
    path(root + "/<uuid:pk>", views.DocumentDetail.as_view()),
    path(root + "/<uuid:pk>/copy", views.DocumentCopy.as_view()),
    path(root + "/<uuid:pk>/download", views.DocumentDownload.as_view()),
    path(root + "/<uuid:pk>/shares", views.DocumentShares.as_view()),
    path(root + "/<uuid:pk>/conversation", views.DocumentConversation.as_view()),
    path(root + "/<uuid:pk>/assistant", views.DocumentAssistant.as_view()),
    path(root + "/<uuid:pk>/runs/<uuid:run_id>/commands", views.DocumentRunCommands.as_view()),
]

from django.urls import path
from . import views
from .media import ContentView

root = "applications/<int:application_id>/my-drive"
urlpatterns = [
    path(root, views.EntryList.as_view()),
    path(root + "/actions", views.Actions.as_view()),
    path(root + "/uploads", views.UploadList.as_view()),
    path(root + "/uploads/<uuid:pk>", views.UploadDetail.as_view()),
    path(root + "/uploads/<uuid:pk>/chunk", views.UploadChunk.as_view()),
    path(root + "/uploads/<uuid:pk>/complete", views.UploadComplete.as_view()),
    path(root + "/entries/<uuid:pk>/access", views.EntryAccess.as_view()),
    path(root + "/content", ContentView.as_view()),
]

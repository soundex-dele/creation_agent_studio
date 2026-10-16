from django.urls import path
from .views import StateView, ImagesView, ImageView, TasksView, TaskView, CancelView, ExportView

prefix = 'applications/<int:application_id>/song-curator/'
urlpatterns = [
    path(prefix + 'state', StateView.as_view()),
    path(prefix + 'images', ImagesView.as_view()),
    path(prefix + 'images/<uuid:image_id>', ImageView.as_view()),
    path(prefix + 'tasks', TasksView.as_view()),
    path(prefix + 'tasks/<uuid:task_id>', TaskView.as_view()),
    path(prefix + 'tasks/<uuid:task_id>/cancel', CancelView.as_view()),
    path(prefix + 'playlists/<uuid:playlist_id>/export', ExportView.as_view()),
]

from django.urls import path
from .views import Records, Versions, Download, Metrics, Settings, Match, Overview, BuiltinPersonas
from .ai import Tasks, Cancel, Apply

prefix = 'applications/<int:application_id>/rental-growth-assistant/'
urlpatterns = [
    path(prefix + 'settings', Settings.as_view()),
    path(prefix + 'personas/built-ins', BuiltinPersonas.as_view()),
    path(prefix + 'ai/tasks', Tasks.as_view()),
    path(prefix + 'ai/tasks/<uuid:task_id>', Tasks.as_view()),
    path(prefix + 'ai/tasks/<uuid:task_id>/cancel', Cancel.as_view()),
    path(prefix + 'ai/tasks/<uuid:task_id>/apply', Apply.as_view()),
    path(prefix + 'overview/<str:section>', Overview.as_view()),
    path(prefix + 'contents/<uuid:record_id>/versions', Versions.as_view()),
    path(prefix + 'versions/<uuid:version_id>/download', Download.as_view()),
    path(prefix + 'publications/<uuid:record_id>/metrics', Metrics.as_view()),
    path(prefix + 'leads/<uuid:record_id>/matches', Match.as_view()),
    path(prefix + '<str:resource>', Records.as_view()),
    path(prefix + '<str:resource>/<uuid:record_id>', Records.as_view()),
]

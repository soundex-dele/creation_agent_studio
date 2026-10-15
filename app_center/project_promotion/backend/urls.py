from django.urls import path
from .views import Records, Versions, ConfirmVersion, Download, Report
from .ai import Tasks, Apply, Cancel
from .integrations import Integrations, Handoffs, HandoffDetail, HandoffResults

prefix = 'applications/<int:application_id>/project-promotion/'
urlpatterns = [
    path(prefix + 'integrations', Integrations.as_view()),
    path(prefix + 'handoffs', Handoffs.as_view()),
    path(prefix + 'handoffs/<uuid:handoff_id>', HandoffDetail.as_view()),
    path(prefix + 'handoffs/<uuid:handoff_id>/results', HandoffResults.as_view()),
    path(prefix + 'report', Report.as_view()),
    path(prefix + 'ai/tasks', Tasks.as_view()),
    path(prefix + 'ai/tasks/<uuid:task_id>', Tasks.as_view()),
    path(prefix + 'ai/tasks/<uuid:task_id>/apply', Apply.as_view()),
    path(prefix + 'ai/tasks/<uuid:task_id>/cancel', Cancel.as_view()),
    path(prefix + 'channels/<uuid:record_id>/versions', Versions.as_view()),
    path(prefix + 'channels/<uuid:record_id>/versions/<uuid:version_id>/confirm', ConfirmVersion.as_view()),
    path(prefix + 'channels/<uuid:record_id>/versions/<uuid:version_id>/download', Download.as_view()),
    path(prefix + '<str:resource>', Records.as_view()),
    path(prefix + '<str:resource>/<uuid:record_id>', Records.as_view()),
]

from django.urls import path
from .views import KitchenStateView, KitchenHistoryView, KitchenRecordView, KitchenCatalogView

from .ai import AITasksView, AITaskView, AITaskCancelView

prefix = "applications/<int:application_id>/kitchen-assistant/"
urlpatterns = [
    path(prefix + "catalog", KitchenCatalogView.as_view()),
    path(prefix + "ai/tasks", AITasksView.as_view()),
    path(prefix + "ai/tasks/<uuid:task_id>", AITaskView.as_view()),
    path(prefix + "ai/tasks/<uuid:task_id>/cancel", AITaskCancelView.as_view()),
    path(prefix + "state", KitchenStateView.as_view()),
    path(prefix + "records", KitchenHistoryView.as_view()),
    path(prefix + "records/<str:record_id>", KitchenRecordView.as_view()),
]

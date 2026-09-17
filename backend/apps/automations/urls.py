from django.urls import path

from .views import (
    AutomationActionView,
    AutomationDisableView,
    AutomationEnableView,
    AutomationRotateSecretView,
    AutomationRunView,
    AutomationTakeOverView,
    AutomationDetailView,
    AutomationInvocationListView,
    AutomationListCreateView,
    AutomationTargetListView,
    SchedulePreviewView,
)


urlpatterns = [
    path("automations", AutomationListCreateView.as_view(), name="automation-list"),
    path("automations/schedule-preview", SchedulePreviewView.as_view(), name="automation-schedule-preview"),
    path("automation-targets", AutomationTargetListView.as_view(), name="automation-targets"),
    path("automations/<int:automation_id>", AutomationDetailView.as_view(), name="automation-detail"),
    path("automations/<int:automation_id>/invocations", AutomationInvocationListView.as_view(), name="automation-invocations"),
    path("automations/<int:automation_id>/enable", AutomationEnableView.as_view(), name="automation-enable"),
    path("automations/<int:automation_id>/disable", AutomationDisableView.as_view(), name="automation-disable"),
    path("automations/<int:automation_id>/run", AutomationRunView.as_view(), name="automation-run"),
    path("automations/<int:automation_id>/rotate-secret", AutomationRotateSecretView.as_view(), name="automation-rotate-secret"),
    path("automations/<int:automation_id>/take-over", AutomationTakeOverView.as_view(), name="automation-take-over"),
]

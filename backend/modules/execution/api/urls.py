from django.urls import path

from .views import (
    OrganizationApplicationRunsView,
    OrganizationRunArtifactsView,
    OrganizationRunArtifactAccessView,
    OrganizationRunEventSnapshotView,
    OrganizationRunAttemptsView,
    OrganizationRunCommandsView,
    OrganizationRunEventsView,
    OrganizationRunStreamView,
    OrganizationRunView,
    RunArtifactContentView,
)


app_name = "execution"

urlpatterns = [
    path(
        "applications/<int:application_id>/runs",
        OrganizationApplicationRunsView.as_view(),
        name="application-runs",
    ),
    path("runs/<uuid:run_id>", OrganizationRunView.as_view(), name="run-detail"),
    path(
        "runs/<uuid:run_id>/events",
        OrganizationRunEventsView.as_view(),
        name="run-events",
    ),
    path(
        "runs/<uuid:run_id>/attempts",
        OrganizationRunAttemptsView.as_view(),
        name="run-attempts",
    ),
    path(
        "runs/<uuid:run_id>/artifacts",
        OrganizationRunArtifactsView.as_view(),
        name="run-artifacts",
    ),
    path(
        "runs/<uuid:run_id>/artifacts/<uuid:artifact_id>/access",
        OrganizationRunArtifactAccessView.as_view(),
        name="run-artifact-access",
    ),
    path(
        "runs/<uuid:run_id>/artifacts/<uuid:artifact_id>/content",
        RunArtifactContentView.as_view(),
        name="run-artifact-content",
    ),
    path(
        "runs/<uuid:run_id>/snapshot",
        OrganizationRunEventSnapshotView.as_view(),
        name="run-event-snapshot",
    ),
    path(
        "runs/<uuid:run_id>/stream",
        OrganizationRunStreamView.as_view(),
        name="run-stream",
    ),
    path(
        "runs/<uuid:run_id>/commands",
        OrganizationRunCommandsView.as_view(),
        name="run-commands",
    ),
]

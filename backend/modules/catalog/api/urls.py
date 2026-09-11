from django.urls import path

from .views import (
    OrganizationApplicationDeploymentRollbackView,
    OrganizationApplicationDeploymentView,
    OrganizationApplicationDeploymentsView,
    OrganizationApplicationDraftView,
    OrganizationApplicationRevisionView,
    OrganizationApplicationRevisionsView,
    OrganizationApplicationsView,
    OrganizationApplicationView,
    OrganizationApplicationRuntimeView,
)


app_name = "catalog"

urlpatterns = [
    path("applications", OrganizationApplicationsView.as_view(), name="application-list"),
    path(
        "applications/<int:application_id>",
        OrganizationApplicationView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/<int:application_id>/runtime",
        OrganizationApplicationRuntimeView.as_view(),
        name="application-runtime",
    ),
    path(
        "applications/<int:application_id>/draft",
        OrganizationApplicationDraftView.as_view(),
        name="application-draft",
    ),
    path(
        "applications/<int:application_id>/revisions",
        OrganizationApplicationRevisionsView.as_view(),
        name="application-revisions",
    ),
    path(
        "applications/<int:application_id>/revisions/<uuid:revision_id>",
        OrganizationApplicationRevisionView.as_view(),
        name="application-revision-detail",
    ),
    path(
        "applications/<int:application_id>/deployments",
        OrganizationApplicationDeploymentsView.as_view(),
        name="application-deployments",
    ),
    path(
        "applications/<int:application_id>/deployments/<str:environment>",
        OrganizationApplicationDeploymentView.as_view(),
        name="application-deployment",
    ),
    path(
        "applications/<int:application_id>/deployments/<str:environment>/rollback",
        OrganizationApplicationDeploymentRollbackView.as_view(),
        name="application-deployment-rollback",
    ),
]

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


app_name = "v2-catalog"

urlpatterns = [
    path("applications", OrganizationApplicationsView.as_view(), name="application-list"),
    path(
        "applications/<uuid:application_id>",
        OrganizationApplicationView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/<uuid:application_id>/runtime",
        OrganizationApplicationRuntimeView.as_view(),
        name="application-runtime",
    ),
    path(
        "applications/<uuid:application_id>/draft",
        OrganizationApplicationDraftView.as_view(),
        name="application-draft",
    ),
    path(
        "applications/<uuid:application_id>/revisions",
        OrganizationApplicationRevisionsView.as_view(),
        name="application-revisions",
    ),
    path(
        "applications/<uuid:application_id>/revisions/<uuid:revision_id>",
        OrganizationApplicationRevisionView.as_view(),
        name="application-revision-detail",
    ),
    path(
        "applications/<uuid:application_id>/deployments",
        OrganizationApplicationDeploymentsView.as_view(),
        name="application-deployments",
    ),
    path(
        "applications/<uuid:application_id>/deployments/<str:environment>",
        OrganizationApplicationDeploymentView.as_view(),
        name="application-deployment",
    ),
    path(
        "applications/<uuid:application_id>/deployments/<str:environment>/rollback",
        OrganizationApplicationDeploymentRollbackView.as_view(),
        name="application-deployment-rollback",
    ),
]

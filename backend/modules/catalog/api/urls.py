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
    OrganizationSkillDeploymentRollbackView,
    OrganizationSkillDeploymentView,
    OrganizationSkillDeploymentsView,
    OrganizationSkillDraftView,
    OrganizationSkillRevisionView,
    OrganizationSkillRevisionsView,
)


app_name = "catalog"

urlpatterns = [
    path("skills/<uuid:skill_id>/draft", OrganizationSkillDraftView.as_view(), name="skill-draft"),
    path("skills/<uuid:skill_id>/revisions", OrganizationSkillRevisionsView.as_view(), name="skill-revisions"),
    path("skills/<uuid:skill_id>/revisions/<uuid:revision_id>", OrganizationSkillRevisionView.as_view(), name="skill-revision-detail"),
    path("skills/<uuid:skill_id>/deployments", OrganizationSkillDeploymentsView.as_view(), name="skill-deployments"),
    path("skills/<uuid:skill_id>/deployments/<str:environment>", OrganizationSkillDeploymentView.as_view(), name="skill-deployment"),
    path("skills/<uuid:skill_id>/deployments/<str:environment>/rollback", OrganizationSkillDeploymentRollbackView.as_view(), name="skill-deployment-rollback"),
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

from importlib import import_module

import pytest
from django.contrib.auth import get_user_model
from django.apps import apps
from django.test import override_settings
from rest_framework.test import APIClient

from apps.agents.models import Agent as ProductAgent, AgentCategory
from apps.applications.models import Application as ProductApplication
from apps.enterprise.models import Membership, Organization
from modules.catalog.models import (
    Agent,
    AgentDeployment,
    AgentDraft,
    AgentRevision,
    Application,
    ApplicationDraft,
)


@pytest.fixture
def unified_context(db):
    user = get_user_model().objects.create_user(username="unified-owner")
    organization = Organization.objects.create(
        name="Unified Organization",
        slug="unified-organization",
        owner=user,
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Membership.Role.OWNER,
    )
    client = APIClient()
    client.force_authenticate(user)
    return user, organization, client


def test_catalog_exports_the_product_entities():
    assert Agent is ProductAgent
    assert Application is ProductApplication


@pytest.mark.django_db
@override_settings(SINGLE_TENANT_MODE=True)
def test_seeded_general_agent_has_a_production_deployment():
    migration = import_module(
        "modules.catalog.migrations.0004_deploy_seeded_general_agent"
    )
    migration.deploy_seeded_general_agent(apps, None)

    agent = ProductAgent.objects.get(slug="general")
    draft = AgentDraft.objects.get(agent=agent)
    deployment = AgentDeployment.objects.select_related("revision").get(
        agent=agent,
        environment="production",
    )

    assert deployment.organization_id == agent.organization_id
    assert deployment.revision.content == draft.content


@pytest.mark.django_db
def test_product_agent_uses_one_draft_revision_and_deployment(unified_context):
    user, organization, client = unified_context
    category = AgentCategory.objects.create(name="Unified", slug="unified")
    response = client.post(
        "/api/agents/",
        {
            "category": category.id,
            "name": "Unified Agent",
            "slug": "unified-agent",
            "description": "One canonical agent",
            "system_prompt": "Be useful.",
            "is_public": False,
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(organization.id),
    )
    assert response.status_code == 201
    agent = ProductAgent.objects.get(pk=response.data["id"])
    draft = AgentDraft.objects.get(agent=agent)
    assert draft.organization_id == organization.id

    version = client.post(
        f"/api/agents/{agent.id}/versions/",
        {"release_notes": "first unified revision"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(organization.id),
    )
    assert version.status_code == 201
    revision = AgentRevision.objects.get(pk=version.data["id"])

    deployed = client.post(
        f"/api/agents/{agent.id}/deploy/",
        {
            "environment": "development",
            "revision_id": str(revision.id),
            "expected_version": 0,
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(organization.id),
    )
    assert deployed.status_code == 200
    deployment = AgentDeployment.objects.get(agent=agent)
    assert deployment.revision_id == revision.id
    assert deployment.updated_by_id == user.id


@pytest.mark.django_db
def test_catalog_application_is_the_same_product_application(unified_context):
    _user, organization, client = unified_context
    response = client.post(
        f"/api/organizations/{organization.id}/applications",
        {
            "name": "Unified Application",
            "slug": "unified-application",
            "description": "One canonical application",
            "content": {
                "executor_kind": "media",
                "executor_key": "unified-executor",
            },
        },
        format="json",
    )
    assert response.status_code == 201
    application = ProductApplication.objects.get(pk=response.data["id"])
    assert Application.objects.get(pk=application.pk) == application
    assert ApplicationDraft.objects.get(application=application).organization_id == organization.id

    product_response = client.get(
        f"/api/apps/{application.slug}/",
        HTTP_X_ORGANIZATION_ID=str(organization.id),
    )
    assert product_response.status_code == 200
    assert product_response.data["id"] == application.id

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory, SupervisorProfile
from apps.enterprise.models import Membership
from modules.execution.application.runs import create_run
from modules.execution.models import Run


@pytest.mark.django_db(transaction=True)
def test_supervisor_create_defaults_to_private_and_is_hidden_from_other_members():
    owner = get_user_model().objects.create_user(username="delegate-owner")
    teammate = get_user_model().objects.create_user(username="delegate-viewer")
    organization = owner.owned_organizations.get()
    Membership.objects.create(
        organization=organization,
        user=teammate,
        role=Membership.Role.VIEWER,
    )
    category = AgentCategory.objects.create(name="Worker", slug="worker")
    worker = Agent.objects.create(
        category=category,
        name="Writer",
        slug="writer",
        description="Writes",
        created_by=owner,
        organization=organization,
        is_public=False,
    )
    url = f"/api/v1/organizations/{organization.id}/delegates"
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(url, {
        "name": "Chief of Staff",
        "slug": "chief-of-staff",
        "description": "Coordinates work",
        "role_prompt": "Plan and delegate work.",
        "agent_ids": [worker.id],
        "application_ids": [],
        "model_config": {},
        "limits": {},
    }, format="json")
    assert response.status_code == 201, response.data
    delegate = Agent.objects.get(pk=response.data["id"])
    assert delegate.kind == Agent.Kind.SUPERVISOR
    assert delegate.supervisor_profile.visibility == SupervisorProfile.Visibility.PRIVATE
    assert delegate.draft.content["orchestration_config"]["agent_ids"] == [worker.id]
    private_run = create_run(
        organization=organization,
        owner=owner,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="supervisor",
        source_type="supervisor",
        source_id=str(delegate.id),
        definition_snapshot={},
        input_data={"goal": "private"},
    )

    client.force_authenticate(teammate)
    assert client.get(url).json() == []
    runs = client.get(f"/api/v1/organizations/{organization.id}/runs")
    assert all(item["id"] != str(private_run.id) for item in runs.json())
    detail = client.get(
        f"/api/v1/organizations/{organization.id}/runs/{private_run.id}"
    )
    assert detail.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_organization_shared_supervisor_is_visible_to_members():
    owner = get_user_model().objects.create_user(username="shared-owner")
    teammate = get_user_model().objects.create_user(username="shared-viewer")
    organization = owner.owned_organizations.get()
    Membership.objects.create(
        organization=organization,
        user=teammate,
        role=Membership.Role.VIEWER,
    )
    category = AgentCategory.objects.create(name="Worker Shared", slug="worker-shared")
    worker = Agent.objects.create(
        category=category,
        name="Researcher",
        slug="researcher",
        description="Researches",
        created_by=owner,
        organization=organization,
    )
    url = f"/api/v1/organizations/{organization.id}/delegates"
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(url, {
        "name": "Shared Lead",
        "slug": "shared-lead",
        "role_prompt": "Coordinate.",
        "visibility": "organization",
        "agent_ids": [worker.id],
    }, format="json")
    assert response.status_code == 201, response.data

    client.force_authenticate(teammate)
    visible = client.get(url)
    assert visible.status_code == 200
    assert [item["slug"] for item in visible.json()] == ["shared-lead"]
    assert visible.json()[0]["can_edit"] is False

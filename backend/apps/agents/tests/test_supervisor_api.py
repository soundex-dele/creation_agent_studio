import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory, SupervisorProfile
from apps.enterprise.models import Membership
from modules.execution.application.runs import create_run
from modules.execution.models import Run


@pytest.mark.django_db
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
        visibility=Agent.Visibility.ORGANIZATION,
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
    assert delegate.visibility == Agent.Visibility.PRIVATE
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


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_deleted_supervisor_slug_can_be_reused():
    owner = get_user_model().objects.create_user(username="delegate-recreate-owner")
    organization = owner.owned_organizations.get()
    category = AgentCategory.objects.create(
        name="Worker Recreate",
        slug="worker-recreate",
    )
    worker = Agent.objects.create(
        category=category,
        name="Worker",
        slug="recreate-worker",
        description="Executes tasks",
        created_by=owner,
        organization=organization,
        is_public=False,
    )
    url = f"/api/v1/organizations/{organization.id}/delegates"
    payload = {
        "name": "Reusable Lead",
        "slug": "reusable-lead",
        "role_prompt": "Plan and coordinate.",
        "agent_ids": [worker.id],
    }
    client = APIClient()
    client.force_authenticate(owner)

    created = client.post(url, payload, format="json")
    assert created.status_code == 201, created.data
    original_id = created.data["id"]
    create_run(
        organization=organization,
        owner=owner,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="supervisor",
        source_type="supervisor",
        source_id=str(original_id),
        definition_snapshot={},
        input_data={"goal": "retain audit history"},
    )

    deleted = client.delete(f"{url}/{original_id}")
    assert deleted.status_code == 204
    assert Agent.objects.filter(pk=original_id, is_active=False).exists()

    recreated = client.post(url, payload, format="json")
    assert recreated.status_code == 201, recreated.data
    assert recreated.data["id"] != original_id
    assert Agent.objects.filter(
        organization=organization,
        slug="reusable-lead",
        is_active=True,
    ).count() == 1


@pytest.mark.django_db
def test_supervisor_publish_names_team_members_without_deployments():
    owner = get_user_model().objects.create_user(username="delegate-validation-owner")
    organization = owner.owned_organizations.get()
    category = AgentCategory.objects.create(
        name="Worker Validation",
        slug="worker-validation",
    )
    worker = Agent.objects.create(
        category=category,
        name="Content Expert",
        slug="content-expert-validation",
        description="Creates content",
        created_by=owner,
        organization=organization,
        is_public=False,
        visibility=Agent.Visibility.ORGANIZATION,
    )
    url = f"/api/v1/organizations/{organization.id}/delegates"
    client = APIClient()
    client.force_authenticate(owner)
    created = client.post(url, {
        "name": "Validation Lead",
        "slug": "validation-lead",
        "role_prompt": "Plan and coordinate.",
        "agent_ids": [worker.id],
    }, format="json")
    assert created.status_code == 201, created.data

    published = client.post(
        f"{url}/{created.data['id']}/publish",
        {"expected_draft_version": created.data["draft_version"]},
        format="json",
    )

    assert published.status_code == 400, published.data
    assert published.data["team"] == (
        f"以下智能体尚未部署：Content Expert（ID {worker.id}）。"
        "请先在“企业管理 → 智能体发布”中激活版本"
    )


@pytest.mark.django_db
def test_supervisor_toggle_does_not_grant_update_or_delete():
    owner = get_user_model().objects.create_user(
        username="delegate-capability-owner",
    )
    operator = get_user_model().objects.create_user(
        username="delegate-toggle-operator",
    )
    organization = owner.owned_organizations.get()
    Membership.objects.create(
        organization=organization,
        user=operator,
        role=Membership.Role.OPERATOR,
    )
    category = AgentCategory.objects.create(
        name="Supervisor Capability",
        slug="supervisor-capability",
    )
    delegate = Agent.objects.create(
        category=category,
        name="Toggle Only Lead",
        slug="toggle-only-lead",
        created_by=owner,
        organization=organization,
        kind=Agent.Kind.SUPERVISOR,
        visibility=Agent.Visibility.ORGANIZATION,
    )
    SupervisorProfile.objects.create(agent=delegate)

    client = APIClient()
    client.force_authenticate(operator)
    url = f"/api/v1/organizations/{organization.id}/delegates/{delegate.id}"

    disabled = client.patch(
        f"{url}/status", {"is_active": False}, format="json"
    )
    assert disabled.status_code == 200, disabled.data
    assert disabled.data["is_active"] is False
    assert disabled.data["can_toggle"] is True
    assert disabled.data["can_edit"] is False
    assert disabled.data["can_delete"] is False

    assert client.patch(
        url, {"name": "Forbidden update"}, format="json"
    ).status_code == 403
    assert client.delete(url).status_code == 403

    enabled = client.patch(
        f"{url}/status", {"is_active": True}, format="json"
    )
    assert enabled.status_code == 200, enabled.data
    assert enabled.data["is_active"] is True

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from modules.catalog.models import (
    ApplicationDeployment,
    ApplicationRevision,
    SkillDeployment,
    SkillRevision,
)
from apps.applications.models import Application, ApplicationCategory, Skill
from apps.enterprise.models import (
    EvaluationRun,
    EvaluationSuite,
    Membership,
    Organization,
)


@pytest.fixture
def catalog_api_owner(db):
    return get_user_model().objects.create_user(username="catalog-api-owner")


@pytest.fixture
def catalog_api_organization(catalog_api_owner):
    organization = Organization.objects.create(
        name="Catalog API Organization",
        slug="catalog-api-organization",
        owner=catalog_api_owner,
    )
    Membership.objects.create(
        organization=organization,
        user=catalog_api_owner,
        role=Membership.Role.OWNER,
    )
    return organization


@pytest.fixture
def catalog_api_client(catalog_api_owner):
    client = APIClient()
    client.force_authenticate(catalog_api_owner)
    return client


def _applications_url(organization):
    return f"/api/v1/organizations/{organization.id}/applications"


def _application_url(organization, application, suffix=""):
    return (
        f"/api/v1/organizations/{organization.id}/applications/"
        f"{application.id}{suffix}"
    )


def _create_application(client, organization, slug="video-editor"):
    response = client.post(
        _applications_url(organization),
        {
            "name": "Video Editor",
            "slug": slug,
            "description": "A versioned application",
            "content": {
                "executor_kind": "media",
                "executor_key": "video-editor",
            },
        },
        format="json",
    )
    assert response.status_code == 201
    return Application.objects.get(pk=response.data["id"]), response


def _publish(client, organization, application, expected_version):
    return client.post(
        _application_url(organization, application, "/revisions"),
        {
            "expected_draft_version": expected_version,
            "release_notes": f"revision from draft {expected_version}",
        },
        format="json",
    )


def _create_skill(client, organization, slug="storyboard"):
    response = client.post(
        "/api/v1/apps/skills/",
        {
            "slug": slug,
            "name": "Storyboard",
            "description": "A versioned skill",
            "visibility": "organization",
            "source_type": "git",
            "source_uri": "https://example.invalid/storyboard.git",
            "manifest": {"entrypoint": "SKILL.md"},
        },
        format="json",
        HTTP_X_ORGANIZATION_ID=str(organization.id),
    )
    assert response.status_code == 201, response.data
    return Skill.objects.get(pk=response.data["id"])


def _skill_url(organization, skill, suffix=""):
    return f"/api/v1/organizations/{organization.id}/skills/{skill.id}{suffix}"


def _publish_skill(client, organization, skill, expected_version):
    return client.post(
        _skill_url(organization, skill, "/revisions"),
        {
            "expected_draft_version": expected_version,
            "release_notes": f"revision from draft {expected_version}",
        },
        format="json",
    )


@pytest.mark.django_db
def test_create_application_atomically_creates_versioned_draft(
    catalog_api_client, catalog_api_organization
):
    application, response = _create_application(
        catalog_api_client, catalog_api_organization
    )

    assert response.data["organization_id"] == str(catalog_api_organization.id)
    assert response.data["draft"]["version"] == 1
    assert response.data["draft"]["application_id"] == application.id
    assert response.data["draft"]["content"]["executor_key"] == "video-editor"

    duplicate = catalog_api_client.post(
        _applications_url(catalog_api_organization),
        {
            "name": "Duplicate",
            "slug": "video-editor",
            "content": {},
        },
        format="json",
    )
    assert duplicate.status_code == 409
    assert duplicate.data["code"] == "application_slug_conflict"


@pytest.mark.django_db
def test_draft_update_uses_optimistic_version(
    catalog_api_client, catalog_api_organization
):
    application, _ = _create_application(
        catalog_api_client, catalog_api_organization
    )
    url = _application_url(catalog_api_organization, application, "/draft")

    updated = catalog_api_client.put(
        url,
        {"expected_version": 1, "content": {"executor_key": "editor-next"}},
        format="json",
    )
    stale = catalog_api_client.put(
        url,
        {"expected_version": 1, "content": {"executor_key": "lost-write"}},
        format="json",
    )

    assert updated.status_code == 200
    assert updated.data["version"] == 2
    assert stale.status_code == 409
    assert stale.data["code"] == "draft_version_conflict"
    application.draft.refresh_from_db()
    assert application.draft.content == {"executor_key": "editor-next"}


@pytest.mark.django_db
def test_publish_is_content_idempotent_and_rejects_stale_draft(
    catalog_api_client, catalog_api_organization
):
    application, _ = _create_application(
        catalog_api_client, catalog_api_organization
    )

    created = _publish(catalog_api_client, catalog_api_organization, application, 1)
    replayed = _publish(catalog_api_client, catalog_api_organization, application, 1)
    stale = _publish(catalog_api_client, catalog_api_organization, application, 2)

    assert created.status_code == 201
    assert created.data["revision_no"] == 1
    assert replayed.status_code == 200
    assert replayed["Idempotent-Replay"] == "true"
    assert replayed.data["id"] == created.data["id"]
    assert stale.status_code == 409
    assert stale.data["code"] == "draft_version_conflict"


@pytest.mark.django_db
def test_publish_rejects_invalid_application_contract(
    catalog_api_client, catalog_api_organization
):
    response = catalog_api_client.post(
        _applications_url(catalog_api_organization),
        {
            "name": "Incomplete Application",
            "slug": "incomplete-application",
            "content": {"renderer_key": "generic-form"},
        },
        format="json",
    )
    application = Application.objects.get(pk=response.data["id"])

    published = _publish(
        catalog_api_client, catalog_api_organization, application, 1
    )

    assert published.status_code == 422
    assert published.data["code"] == "invalid_application_definition"
    assert {error["field"] for error in published.data["errors"]} == {
        "executor_kind",
        "executor_key",
    }
    assert application.revisions.count() == 0


@pytest.mark.django_db
def test_deployment_switch_and_rollback_are_versioned(
    catalog_api_client, catalog_api_organization
):
    application, _ = _create_application(
        catalog_api_client, catalog_api_organization
    )
    first_response = _publish(
        catalog_api_client, catalog_api_organization, application, 1
    )
    first_revision = ApplicationRevision.objects.get(pk=first_response.data["id"])
    draft_url = _application_url(catalog_api_organization, application, "/draft")
    update = catalog_api_client.put(
        draft_url,
        {
            "expected_version": 1,
            "content": {
                "executor_kind": "media",
                "executor_key": "video-editor-next",
            },
        },
        format="json",
    )
    assert update.status_code == 200
    second_response = _publish(
        catalog_api_client, catalog_api_organization, application, 2
    )
    second_revision = ApplicationRevision.objects.get(pk=second_response.data["id"])
    deployment_url = _application_url(
        catalog_api_organization, application, "/deployments/development"
    )

    created = catalog_api_client.put(
        deployment_url,
        {
            "revision_id": str(first_revision.id),
            "expected_version": 0,
            "config_override": {"quality": "preview"},
        },
        format="json",
    )
    switched = catalog_api_client.put(
        deployment_url,
        {
            "revision_id": str(second_revision.id),
            "expected_version": 1,
            "config_override": {"quality": "high"},
        },
        format="json",
    )
    rolled_back = catalog_api_client.post(
        f"{deployment_url}/rollback",
        {"expected_version": 2},
        format="json",
    )
    database_version_after_rollback = ApplicationDeployment.objects.get(
        application=application,
        environment="development",
    ).version
    stale = catalog_api_client.put(
        deployment_url,
        {
            "revision_id": str(second_revision.id),
            "expected_version": 2,
        },
        format="json",
    )

    assert created.status_code == 201
    assert created.data["version"] == 1
    assert switched.status_code == 200
    assert switched.data["revision_id"] == str(second_revision.id)
    assert switched.data["previous_revision_id"] == str(first_revision.id)
    assert rolled_back.status_code == 200
    assert rolled_back.data["version"] == 3
    assert database_version_after_rollback == 3
    assert rolled_back.data["revision_id"] == str(first_revision.id)
    assert rolled_back.data["previous_revision_id"] == str(second_revision.id)
    assert stale.status_code == 409, stale.data
    assert stale.data["code"] == "deployment_version_conflict"


@pytest.mark.django_db
def test_deployment_rejects_revision_from_another_application(
    catalog_api_client, catalog_api_organization
):
    application, _ = _create_application(
        catalog_api_client, catalog_api_organization, "first-application"
    )
    other, _ = _create_application(
        catalog_api_client, catalog_api_organization, "other-application"
    )
    other_revision_response = _publish(
        catalog_api_client, catalog_api_organization, other, 1
    )

    response = catalog_api_client.put(
        _application_url(
            catalog_api_organization, application, "/deployments/development"
        ),
        {
            "revision_id": other_revision_response.data["id"],
            "expected_version": 0,
        },
        format="json",
    )

    assert response.status_code == 422
    assert response.data["code"] == "invalid_deployment_revision"


@pytest.mark.django_db
def test_production_deployment_requires_admin_role(
    catalog_api_client, catalog_api_owner, catalog_api_organization
):
    application, _ = _create_application(
        catalog_api_client, catalog_api_organization
    )
    revision_response = _publish(
        catalog_api_client, catalog_api_organization, application, 1
    )
    developer = get_user_model().objects.create_user(username="catalog-api-developer")
    Membership.objects.create(
        organization=catalog_api_organization,
        user=developer,
        role=Membership.Role.DEVELOPER,
    )
    developer_client = APIClient()
    developer_client.force_authenticate(developer)
    url = _application_url(
        catalog_api_organization, application, "/deployments/production"
    )
    payload = {"revision_id": revision_response.data["id"], "expected_version": 0}

    denied = developer_client.put(url, payload, format="json")
    accepted = catalog_api_client.put(url, payload, format="json")

    assert denied.status_code == 403
    assert denied.data["code"] == "production_deployment_requires_admin"
    assert accepted.status_code == 201


@pytest.mark.django_db
def test_runtime_descriptor_resolves_one_immutable_deployment(
    catalog_api_client, catalog_api_organization
):
    application, _ = _create_application(
        catalog_api_client, catalog_api_organization
    )
    revision = _publish(
        catalog_api_client, catalog_api_organization, application, 1
    )
    deployed = catalog_api_client.put(
        _application_url(
            catalog_api_organization, application, "/deployments/development"
        ),
        {"revision_id": revision.data["id"], "expected_version": 0},
        format="json",
    )
    assert deployed.status_code == 201

    runtime = catalog_api_client.get(
        _application_url(catalog_api_organization, application, "/runtime"),
        {"environment": "development"},
    )

    assert runtime.status_code == 200
    assert runtime.data["application_id"] == str(application.id)
    assert runtime.data["revision_id"] == revision.data["id"]
    assert runtime.data["deployment_version"] == 1
    assert runtime.data["definition"]["executor_key"] == "video-editor"


@pytest.mark.django_db
def test_catalog_resources_are_scoped_to_path_organization(
    catalog_api_client, catalog_api_owner, catalog_api_organization
):
    other = Organization.objects.create(
        name="Other Catalog Organization",
        slug="other-catalog-api-organization",
        owner=catalog_api_owner,
    )
    Membership.objects.create(
        organization=other,
        user=catalog_api_owner,
        role=Membership.Role.OWNER,
    )
    foreign_application = Application.objects.create(
        organization=other,
        created_by=catalog_api_owner,
        category=ApplicationCategory.objects.get_or_create(
            slug="uncategorized", defaults={"name": "Uncategorized"}
        )[0],
        name="Foreign",
        slug="foreign",
        description="Foreign application",
    )

    response = catalog_api_client.get(
        _application_url(catalog_api_organization, foreign_application)
    )

    assert response.status_code == 404
    assert response.data["code"] == "application_not_found"


@pytest.mark.django_db
def test_skill_draft_cas_and_revision_publish_are_content_idempotent(
    catalog_api_client, catalog_api_organization
):
    skill = _create_skill(catalog_api_client, catalog_api_organization)
    draft_url = _skill_url(catalog_api_organization, skill, "/draft")
    content = {
        "source_type": "git",
        "source_uri": "https://example.invalid/storyboard-v2.git",
        "manifest": {"entrypoint": "SKILL.md"},
    }

    updated = catalog_api_client.put(
        draft_url, {"expected_version": 1, "content": content}, format="json"
    )
    stale = catalog_api_client.put(
        draft_url,
        {"expected_version": 1, "content": {"source_type": "upload"}},
        format="json",
    )
    created = _publish_skill(
        catalog_api_client, catalog_api_organization, skill, 2
    )
    replayed = _publish_skill(
        catalog_api_client, catalog_api_organization, skill, 2
    )

    assert updated.status_code == 200
    assert updated.data["version"] == 2
    assert stale.status_code == 409
    assert stale.data["code"] == "draft_version_conflict"
    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed["Idempotent-Replay"] == "true"
    assert replayed.data["id"] == created.data["id"]
    assert SkillRevision.objects.get(pk=created.data["id"]).content == content


@pytest.mark.django_db
def test_skill_deployment_switch_conflict_and_rollback(
    catalog_api_client, catalog_api_organization
):
    skill = _create_skill(catalog_api_client, catalog_api_organization)
    first = _publish_skill(catalog_api_client, catalog_api_organization, skill, 1)
    draft_url = _skill_url(catalog_api_organization, skill, "/draft")
    update = catalog_api_client.put(
        draft_url,
        {"expected_version": 1, "content": {"artifact_key": "skills/storyboard-v2"}},
        format="json",
    )
    assert update.status_code == 200
    second = _publish_skill(catalog_api_client, catalog_api_organization, skill, 2)
    deployment_url = _skill_url(
        catalog_api_organization, skill, "/deployments/development"
    )

    created = catalog_api_client.put(
        deployment_url,
        {"revision_id": first.data["id"], "expected_version": 0},
        format="json",
    )
    conflict = catalog_api_client.put(
        deployment_url,
        {"revision_id": second.data["id"], "expected_version": 0},
        format="json",
    )
    switched = catalog_api_client.put(
        deployment_url,
        {"revision_id": second.data["id"], "expected_version": 1},
        format="json",
    )
    rolled_back = catalog_api_client.post(
        f"{deployment_url}/rollback", {"expected_version": 2}, format="json"
    )

    assert created.status_code == 201
    assert conflict.status_code == 409
    assert conflict.data["code"] == "deployment_version_conflict"
    assert switched.status_code == 200
    assert switched.data["previous_revision_id"] == first.data["id"]
    assert rolled_back.status_code == 200
    assert rolled_back.data["revision_id"] == first.data["id"]
    assert rolled_back.data["previous_revision_id"] == second.data["id"]
    assert SkillDeployment.objects.get(skill=skill).version == 3


@pytest.mark.django_db
def test_skill_production_mutation_requires_admin_but_read_does_not(
    catalog_api_client, catalog_api_organization
):
    skill = _create_skill(catalog_api_client, catalog_api_organization)
    revision = _publish_skill(catalog_api_client, catalog_api_organization, skill, 1)
    url = _skill_url(catalog_api_organization, skill, "/deployments/production")
    payload = {"revision_id": revision.data["id"], "expected_version": 0}
    assert catalog_api_client.put(url, payload, format="json").status_code == 201

    developer = get_user_model().objects.create_user(username="skill-developer")
    Membership.objects.create(
        organization=catalog_api_organization,
        user=developer,
        role=Membership.Role.DEVELOPER,
    )
    developer_client = APIClient()
    developer_client.force_authenticate(developer)

    assert developer_client.get(url).status_code == 200
    denied = developer_client.put(
        url,
        {"revision_id": revision.data["id"], "expected_version": 1},
        format="json",
    )
    assert denied.status_code == 403
    assert denied.data["code"] == "production_deployment_requires_admin"


@pytest.mark.django_db
def test_skill_production_deployment_requires_matching_passed_quality_gate(
    catalog_api_client, catalog_api_owner, catalog_api_organization
):
    skill = _create_skill(catalog_api_client, catalog_api_organization)
    revision = _publish_skill(catalog_api_client, catalog_api_organization, skill, 1)
    suite = EvaluationSuite.objects.create(
        organization=catalog_api_organization,
        name="Skill release gate",
        target_type="skill",
        target_id=str(skill.id),
        quality_gate={"minimum_score": 0.9},
    )
    url = _skill_url(catalog_api_organization, skill, "/deployments/production")
    payload = {"revision_id": revision.data["id"], "expected_version": 0}

    blocked = catalog_api_client.put(url, payload, format="json")
    EvaluationRun.objects.create(
        suite=suite,
        created_by=catalog_api_owner,
        target_version=revision.data["id"],
        status="completed",
        score=1,
        passed=True,
    )
    accepted = catalog_api_client.put(url, payload, format="json")

    assert blocked.status_code == 409
    assert blocked.data["code"] == "quality_gate_not_passed"
    assert accepted.status_code == 201

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership, Organization

from ..models import CreationWorkspace, MediaAsset


@pytest.fixture
def toolbox_context(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    User = get_user_model()
    owner = User.objects.create_user(username="toolbox-owner")
    developer = User.objects.create_user(username="toolbox-developer")
    outsider = User.objects.create_user(username="toolbox-outsider")
    organization = Organization.objects.create(
        name="Toolbox Organization", slug="toolbox-organization", owner=owner
    )
    Membership.objects.create(
        organization=organization, user=owner, role=Membership.Role.OWNER
    )
    Membership.objects.create(
        organization=organization, user=developer, role=Membership.Role.DEVELOPER
    )
    category = ApplicationCategory.objects.create(name="Creative", slug="toolbox-creative")
    application = Application.objects.create(
        organization=organization,
        category=category,
        name="创作工具箱",
        slug="creation-toolbox-test",
        description="Creation Toolbox",
        created_by=owner,
        kind=Application.Kind.CUSTOM,
    )
    workspace = CreationWorkspace.objects.create(
        organization=organization, application=application
    )
    return {
        "owner": owner,
        "developer": developer,
        "outsider": outsider,
        "organization": organization,
        "application": application,
        "workspace": workspace,
    }


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _root(context):
    return (
        f"/api/v1/organizations/{context['organization'].id}/applications/"
        f"{context['application'].id}/creation-toolbox"
    )


@pytest.mark.django_db
def test_project_asset_and_workspace_counts(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    created = client.post(
        f"{root}/projects",
        {"name": "第一期视频", "description": "产品发布"},
        format="json",
    )
    assert created.status_code == 201, created.data
    project_id = created.data["id"]

    folder = client.post(
        f"{root}/projects/{project_id}/folders",
        {"name": "封面素材"},
        format="json",
    )
    assert folder.status_code == 201, folder.data
    folder_list = client.get(f"{root}/projects/{project_id}/folders")
    assert folder_list.status_code == 200, folder_list.data
    assert folder_list.data[0]["name"] == "封面素材"

    uploaded = client.post(
        f"{root}/projects/{project_id}/assets",
        {"file": SimpleUploadedFile("cover.png", b"png-data", content_type="image/png")},
        format="multipart",
    )
    assert uploaded.status_code == 201, uploaded.data
    assert uploaded.data["kind"] == MediaAsset.Kind.IMAGE
    assert uploaded.data["size"] == 8

    workspace = client.get(f"{root}/workspace")
    assert workspace.status_code == 200
    assert workspace.data["project_count"] == 1
    assert workspace.data["asset_count"] == 1


@pytest.mark.django_db
def test_copywriting_and_script_workflow(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    generated = client.post(
        f"{root}/copywritings/generate",
        {"topic": "秋日旅行", "style": "emotional"},
        format="json",
    )
    assert generated.status_code == 201, generated.data
    assert "秋日旅行" in generated.data["content"]

    script = client.post(
        f"{root}/scripts",
        {"title": "秋日旅行短片", "description": "三幕结构"},
        format="json",
    )
    assert script.status_code == 201, script.data
    scene = client.post(
        f"{root}/scripts/{script.data['id']}/scenes",
        {"title": "开场", "description": "落叶特写", "duration_seconds": 6},
        format="json",
    )
    assert scene.status_code == 201, scene.data
    exported = client.get(f"{root}/scripts/{script.data['id']}/export")
    assert exported.status_code == 200
    assert "落叶特写" in exported.data["content"]


@pytest.mark.django_db
def test_tenant_boundary(toolbox_context):
    outsider = _client(toolbox_context["outsider"])
    assert outsider.get(f"{_root(toolbox_context)}/workspace").status_code == 403

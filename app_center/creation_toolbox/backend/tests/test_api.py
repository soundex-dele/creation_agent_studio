import pytest
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
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
    viewer = User.objects.create_user(username="toolbox-viewer")
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
    Membership.objects.create(
        organization=organization, user=viewer, role=Membership.Role.VIEWER
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
        "viewer": viewer,
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
        {
            "folder_id": folder.data["id"],
            "file": SimpleUploadedFile("cover.png", b"png-data", content_type="image/png"),
        },
        format="multipart",
    )
    assert uploaded.status_code == 201, uploaded.data
    assert uploaded.data["kind"] == MediaAsset.Kind.IMAGE
    assert uploaded.data["size"] == 8
    media_url = f"{reverse('private-media')}?token="
    assert uploaded.data["download_url"].startswith(media_url)

    downloaded = client.get(uploaded.data["download_url"])
    assert downloaded.status_code == 200
    assert downloaded["Content-Disposition"].startswith(
        'attachment; filename="cover.png"'
    )
    assert b"".join(downloaded.streaming_content) == b"png-data"
    assert client.get(f"{root}/projects/{project_id}/assets").data == []
    assert len(client.get(f"{root}/projects/{project_id}/assets?all=true").data) == 1

    deliverable = client.post(
        f"{root}/deliverables",
        {
            "project": project_id,
            "name": "发布视频.mp4",
            "file": SimpleUploadedFile("publish.mp4", b"video-data", content_type="video/mp4"),
        },
        format="multipart",
    )
    assert deliverable.status_code == 201, deliverable.data
    assert deliverable.data["download_url"].startswith(media_url)
    video = client.get(deliverable.data["download_url"])
    assert video.status_code == 200
    assert "attachment" in video["Content-Disposition"]
    assert b"".join(video.streaming_content) == b"video-data"

    workspace = client.get(f"{root}/workspace")
    assert workspace.status_code == 200
    assert workspace.data["project_count"] == 1
    assert workspace.data["asset_count"] == 1


@pytest.mark.django_db
def test_copywriting_and_script_workflow(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    created_copy = client.post(
        f"{root}/copywritings",
        {
            "title": "秋日旅行",
            "content": "用户自己记录的文案。",
            "style": "emotional",
        },
        format="json",
    )
    assert created_copy.status_code == 201, created_copy.data
    assert created_copy.data["content"] == "用户自己记录的文案。"
    assert client.post(f"{root}/copywritings/generate", {}, format="json").status_code == 404

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

    viewer = _client(toolbox_context["viewer"])
    assert viewer.get(f"{_root(toolbox_context)}/topics").status_code == 200
    assert viewer.post(
        f"{_root(toolbox_context)}/topics", {"title": "只读用户不能新增"}, format="json"
    ).status_code == 403


@pytest.mark.django_db
def test_topic_duplicate_multi_project_and_delete_guard(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    topic = client.post(
        f"{root}/topics",
        {
            "title": "普通人如何建立知识库",
            "notes": "从真实使用场景切入",
            "tags": ["知识管理", "效率"],
            "target_platforms": ["douyin", "bilibili"],
        },
        format="json",
    )
    assert topic.status_code == 201, topic.data
    duplicate = client.post(
        f"{root}/topics", {"title": "  普通人如何建立知识库  "}, format="json"
    )
    assert duplicate.status_code == 409
    allowed = client.post(
        f"{root}/topics",
        {"title": "普通人如何建立知识库", "allow_duplicate": True},
        format="json",
    )
    assert allowed.status_code == 201, allowed.data

    first = client.post(
        f"{root}/topics/{topic.data['id']}/create-project",
        {"work_type": "image_text", "target_platforms": ["douyin"]},
        format="json",
    )
    second = client.post(
        f"{root}/topics/{topic.data['id']}/create-project",
        {"work_type": "short_video", "target_platforms": ["bilibili"]},
        format="json",
    )
    assert first.status_code == second.status_code == 201
    assert first.data["name"] == "普通人如何建立知识库-图文"
    assert first.data["work_type"] == "image_text"
    assert first.data["work_type_label"] == "图文"
    assert second.data["name"] == "普通人如何建立知识库-短视频"
    duplicate_project = client.post(
        f"{root}/topics/{topic.data['id']}/create-project",
        {"work_type": "image_text"},
        format="json",
    )
    assert duplicate_project.status_code == 400
    detail = client.get(f"{root}/topics/{topic.data['id']}")
    assert detail.data["status"] == "adopted"
    assert len(detail.data["projects"]) == 2
    assert client.delete(f"{root}/topics/{topic.data['id']}").status_code == 409


@pytest.mark.django_db
def test_parent_and_child_topics_can_each_create_projects(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    parent = client.post(
        f"{root}/topics",
        {"title": "AI 创作效率", "notes": "系列选题"},
        format="json",
    )
    assert parent.status_code == 201, parent.data
    assert parent.data["parent"] is None
    assert parent.data["child_count"] == 0

    children = []
    for title in ("AI 如何辅助选题", "AI 如何生成配图"):
        child = client.post(
            f"{root}/topics",
            {"title": title, "parent": parent.data["id"]},
            format="json",
        )
        assert child.status_code == 201, child.data
        assert str(child.data["parent"]) == parent.data["id"]
        assert child.data["parent_title"] == "AI 创作效率"
        children.append(child.data)

    topic_list = client.get(f"{root}/topics")
    assert topic_list.status_code == 200, topic_list.data
    listed_parent = next(item for item in topic_list.data if item["id"] == parent.data["id"])
    assert listed_parent["child_count"] == 2

    edited_child = client.patch(
        f"{root}/topics/{children[1]['id']}",
        {"title": "AI 如何生成配图进阶", "notes": "第一行\n第二行"},
        format="json",
    )
    assert edited_child.status_code == 200, edited_child.data
    assert edited_child.data["title"] == "AI 如何生成配图进阶"
    assert edited_child.data["notes"] == "第一行\n第二行"

    grandchild = client.post(
        f"{root}/topics",
        {"title": "不允许的三级选题", "parent": children[0]["id"]},
        format="json",
    )
    assert grandchild.status_code == 400
    assert "只能在父选题下创建一层子选题" in str(grandchild.data["parent"])

    self_parent = client.patch(
        f"{root}/topics/{parent.data['id']}",
        {"parent": parent.data["id"]},
        format="json",
    )
    assert self_parent.status_code == 400
    assert "不能将选题自身设为父选题" in str(self_parent.data["parent"])

    parent_project = client.post(
        f"{root}/topics/{parent.data['id']}/create-project",
        {"work_type": "long_article"},
        format="json",
    )
    child_project = client.post(
        f"{root}/topics/{children[0]['id']}/create-project",
        {"work_type": "short_video"},
        format="json",
    )
    assert parent_project.status_code == 201, parent_project.data
    assert parent_project.data["name"] == "AI 创作效率-长图文（公众号）"
    assert child_project.status_code == 201, child_project.data
    assert child_project.data["name"] == "AI 如何辅助选题-短视频"

    protected_parent = client.post(
        f"{root}/topics", {"title": "待拆解父选题"}, format="json"
    )
    protected_child = client.post(
        f"{root}/topics",
        {"title": "待拆解子选题", "parent": protected_parent.data["id"]},
        format="json",
    )
    assert protected_child.status_code == 201, protected_child.data
    blocked_delete = client.delete(f"{root}/topics/{protected_parent.data['id']}")
    assert blocked_delete.status_code == 409
    assert "已有子选题" in blocked_delete.data["detail"]


@pytest.mark.django_db
def test_publication_metrics_stage_and_analytics(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    project = client.post(
        f"{root}/projects",
        {
            "name": "产品演示短片",
            "description": "人工策划",
            "planned_publish_at": (timezone.now() - timedelta(days=1)).isoformat(),
        },
        format="json",
    )
    assert project.status_code == 201, project.data
    project_id = project.data["id"]
    blocked = client.post(
        f"{root}/projects/{project_id}/stage-transitions",
        {"to_stage": "retrospective"},
        format="json",
    )
    assert blocked.status_code == 400

    deliverable = client.post(
        f"{root}/deliverables",
        {
            "project": project_id,
            "name": "正式版",
            "version_label": "v1",
            "platform": "douyin",
            "external_url": "https://example.com/final.mp4",
            "review_status": "approved",
        },
        format="json",
    )
    assert deliverable.status_code == 201, deliverable.data
    assert deliverable.data["download_url"] == ""
    publication = client.post(
        f"{root}/publications",
        {
            "project": project_id,
            "deliverable": deliverable.data["id"],
            "platform": "douyin",
            "account_name": "品牌账号",
            "external_post_id": "dy-100",
            "post_url": "https://example.com/posts/dy-100",
            "published_at": timezone.now().isoformat(),
        },
        format="json",
    )
    assert publication.status_code == 201, publication.data
    assert client.get(f"{root}/projects/{project_id}").data["stage"] == "published"
    snapshot = client.post(
        f"{root}/publications/{publication.data['id']}/metrics",
        {
            "observed_on": timezone.localdate().isoformat(),
            "impressions": 1000,
            "views": 800,
            "completions": 400,
            "likes": 80,
            "comments": 20,
            "shares": 10,
            "saves": 10,
            "followers_gained": 8,
            "conversions": 4,
        },
        format="json",
    )
    assert snapshot.status_code == 201, snapshot.data
    assert snapshot.data["play_rate"] == 0.8
    assert snapshot.data["engagement_rate"] == 0.15
    completed = client.post(
        f"{root}/projects/{project_id}/stage-transitions",
        {"to_stage": "retrospective", "note": "完成复盘"},
        format="json",
    )
    assert completed.status_code == 200, completed.data
    analytics = client.get(f"{root}/analytics")
    assert analytics.status_code == 200, analytics.data
    assert analytics.data["summary"]["views"] == 800
    assert analytics.data["summary"]["completion_rate"] == 0.5
    assert analytics.data["topics"]["tag_performance"] == []

    zero_project = client.post(f"{root}/projects", {"name": "零分母工程"}, format="json")
    zero_publication = client.post(
        f"{root}/publications",
        {
            "project": zero_project.data["id"], "platform": "bilibili",
            "account_name": "品牌账号", "external_post_id": "zero-1",
            "published_at": timezone.now().isoformat(),
        },
        format="json",
    )
    zero_snapshot = client.post(
        f"{root}/publications/{zero_publication.data['id']}/metrics",
        {"observed_on": timezone.localdate().isoformat()},
        format="json",
    )
    assert zero_snapshot.status_code == 201, zero_snapshot.data
    assert zero_snapshot.data["play_rate"] is None
    assert zero_snapshot.data["engagement_rate"] is None


@pytest.mark.django_db
def test_metrics_csv_preview_and_commit_are_idempotent(toolbox_context):
    client = _client(toolbox_context["developer"])
    root = _root(toolbox_context)
    project = client.post(f"{root}/projects", {"name": "CSV 工程"}, format="json")
    csv_text = (
        "project_name,platform,platform_name,account_name,title,external_post_id,post_url,"
        "published_at,observed_on,impressions,views,completions,likes,comments,shares,saves,"
        "followers_gained,conversions,average_watch_seconds\n"
        "CSV 工程,douyin,,账号,作品,post-1,https://example.com/post-1,2026-09-20 18:00:00,"
        "2026-09-21,100,80,40,8,2,1,1,1,0,18.5\n"
    )
    preview = client.post(
        f"{root}/metrics-csv/import",
        {"file": SimpleUploadedFile("metrics.csv", csv_text.encode("utf-8"), content_type="text/csv")},
        format="multipart",
    )
    assert preview.status_code == 200, preview.data
    assert preview.data["valid"] is True
    for expected_status in (200, 200):
        committed = client.post(
            f"{root}/metrics-csv/import",
            {
                "commit": "true",
                "file": SimpleUploadedFile("metrics.csv", csv_text.encode("utf-8"), content_type="text/csv"),
            },
            format="multipart",
        )
        assert committed.status_code == expected_status, committed.data
        assert committed.data["publication_count"] == 1
        assert committed.data["snapshot_count"] == 1
    assert client.get(f"{root}/projects/{project.data['id']}").data["stage"] == "published"

    invalid_text = csv_text.replace("18.5", "not-a-number")
    invalid = client.post(
        f"{root}/metrics-csv/import",
        {"file": SimpleUploadedFile("invalid.csv", invalid_text.encode("utf-8"), content_type="text/csv")},
        format="multipart",
    )
    assert invalid.status_code == 400
    assert invalid.data["valid"] is False
    assert invalid.data["errors"][0]["row"] == 2

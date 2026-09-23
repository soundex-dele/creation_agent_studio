import copy
import json
import shutil
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import Application, ApplicationCategory
from apps.conversations.models import Conversation, Message
from apps.enterprise.models import Membership
from modules.catalog.models import AgentDeployment, AgentRevision
from modules.catalog.services import canonical_content_hash
from modules.execution.models import Run
from ..models import Document, DocumentSession


def content(text="正文内容"):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.AGENT_ENGINE_ADAPTER = "codex"
    owner = get_user_model().objects.create_user(username="doc-owner")
    reader = get_user_model().objects.create_user(username="doc-reader")
    outsider = get_user_model().objects.create_user(username="doc-outsider")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=reader, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name="文档测试", slug="doc-test")
    app = Application.objects.create(organization=org, category=category, name="在线文档", slug="documents",
                                     created_by=owner, kind="custom", visibility="organization")
    client = APIClient()
    client.force_authenticate(owner)
    root = f"/api/v1/organizations/{org.id}/applications/{app.id}/documents"
    created = client.post(root, {"title": "测试文档", "content": content()}, format="json")
    assert created.status_code == 201, created.data
    return {"client": client, "owner": owner, "reader": reader, "outsider": outsider, "org": org, "app": app,
            "root": root, "id": created.data["id"], "url": f"{root}/{created.data['id']}"}


def share(ctx, role="viewer"):
    response = ctx["client"].post(ctx["url"] + "/shares", {"user_id": ctx["reader"].id, "role": role}, format="json")
    assert response.status_code == 200, response.data


def deploy_agent(ctx):
    category = AgentCategory.objects.create(name="文档助手", slug="doc-agent-test")
    agent = Agent.objects.create(category=category, organization=ctx["org"], created_by=ctx["owner"],
                                 name="通用", slug="general", visibility="organization")
    definition = {"system_prompt": "You are a writing assistant."}
    revision = AgentRevision.objects.create(organization=ctx["org"], agent=agent, revision_no=1,
        content=definition, content_hash=canonical_content_hash(definition), created_by=ctx["owner"])
    AgentDeployment.objects.create(organization=ctx["org"], agent=agent, revision=revision, updated_by=ctx["owner"])


def send(ctx, **overrides):
    return ctx["client"].post(ctx["url"] + "/assistant", {"content": "请润色", "version": 1, **overrides}, format="json", HTTP_IDEMPOTENCY_KEY="document-turn")


def test_crud_search_copy_download_conflicts(ctx):
    client, root, url = ctx["client"], ctx["root"], ctx["url"]
    assert client.get(root, {"search": "正文"}).data["count"] == 1
    assert "content" not in client.get(root).data["results"][0]
    assert client.get(url).data["permission"] == "owner"
    assert client.patch(url, {"title": "缺少版本"}, format="json").status_code == 400
    updated = client.patch(url, {"title": "新标题", "version": 1, "content": content("新正文")}, format="json")
    assert updated.status_code == 200, updated.data
    assert updated.data["version"] == 2 and updated.data["plain_text"] == "新正文"
    assert client.patch(url, {"version": 1, "content": content("旧草稿")}, format="json").status_code == 409
    assert client.get(url).data["plain_text"] == "新正文"
    assert client.get(url + "/download").content.decode() == "新正文"
    copied = client.post(url + "/copy", {"title": "冲突副本", "content": content("草稿")}, format="json")
    assert copied.status_code == 201 and copied.data["plain_text"] == "草稿" and copied.data["version"] == 1
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_sharing_and_revocation(ctx):
    client, url = ctx["client"], ctx["url"]
    client.force_authenticate(ctx["reader"])
    assert client.get(url).status_code == 404
    assert client.get(ctx["root"], {"scope": "shared"}).data["count"] == 0
    client.force_authenticate(ctx["owner"])
    share(ctx)
    client.force_authenticate(ctx["reader"])
    assert client.get(url).data["permission"] == "viewer"
    assert client.get(ctx["root"], {"scope": "shared"}).data["count"] == 1
    assert client.get(ctx["root"]).data["count"] == 0
    assert client.get(url + "/download").status_code == 200
    assert client.patch(url, {"version": 1, "title": "非法编辑"}, format="json").status_code == 403
    assert client.delete(url).status_code == 403
    assert client.get(url + "/shares").status_code == 403
    client.force_authenticate(ctx["owner"])
    share(ctx, "editor")
    client.force_authenticate(ctx["reader"])
    assert client.patch(url, {"version": 1, "title": "协作标题"}, format="json").status_code == 200
    assert client.post(url + "/shares", {"user_id": ctx["outsider"].id, "role": "editor"}, format="json").status_code == 403
    client.force_authenticate(ctx["owner"])
    assert client.delete(url + f"/shares?user_id={ctx['reader'].id}").status_code == 204
    client.force_authenticate(ctx["reader"])
    assert client.get(url).status_code == 404
    assert client.post(url + "/copy", {}, format="json").status_code == 404


def test_tenant_application_and_inactive_membership(ctx):
    client, url = ctx["client"], ctx["url"]
    assert client.post(url + "/shares", {"user_id": ctx["outsider"].id, "role": "viewer"}, format="json").status_code == 400
    share(ctx)
    client.force_authenticate(ctx["outsider"])
    assert client.get(url).status_code in (403, 404)
    client.force_authenticate(ctx["reader"])
    wrong = url.replace(str(ctx["org"].id), str(ctx["reader"].owned_organizations.get().id))
    assert client.get(wrong).status_code == 404
    assert client.get(url.replace(f"applications/{ctx['app'].id}", "applications/999999")).status_code == 404
    ctx["app"].is_active = False
    ctx["app"].save()
    assert client.get(url).status_code == 404
    ctx["app"].is_active = True
    ctx["app"].save()
    Membership.objects.filter(organization=ctx["org"], user=ctx["reader"]).update(is_active=False)
    assert client.get(url).status_code in (403, 404)


@pytest.mark.parametrize("bad", [
    {"type": "doc", "content": [{"type": "image", "attrs": {"src": "x"}}]},
    {"type": "doc", "content": [{"type": "paragraph", "attrs": {"onclick": "bad"}}]},
    {"type": "doc", "content": [{"type": "listItem", "content": [None]}]},
    {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "table"}]}]},
    {"type": "doc", "content": []},
    {"type": "doc", "content": [{"type": {"bad": "node"}}]},
    {"type": "doc", "content": [{"type": "paragraph", "attrs": []}]},
])
def test_invalid_content(ctx, bad):
    assert ctx["client"].patch(ctx["url"], {"version": 1, "content": bad}, format="json").status_code == 400


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/html,x", "file:///secret", "https://x\n.org"])
def test_unsafe_link(ctx, href):
    value = content()
    value["content"][0]["content"][0]["marks"] = [{"type": "link", "attrs": {"href": href}}]
    assert ctx["client"].patch(ctx["url"], {"version": 1, "content": value}, format="json").status_code == 400


def test_table_and_safe_links(ctx):
    cell = {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None}, "content": content("单元格")["content"]}
    table = {"type": "table", "content": [{"type": "tableRow", "content": [cell, copy.deepcopy(cell)]}]}
    value = content()
    value["content"].append(table)
    value["content"][0]["content"][0]["marks"] = [{"type": "link", "attrs": {"href": "https://example.com", "class": "evil"}}]
    saved = ctx["client"].patch(ctx["url"], {"version": 1, "content": value}, format="json")
    assert saved.status_code == 200, saved.data
    assert "单元格" in saved.data["plain_text"]
    assert "class" not in saved.data["content"]["content"][0]["content"][0]["marks"][0]["attrs"]


def test_actual_editor_json_round_trip(ctx):
    value = json.loads((Path(__file__).parent / "fixtures" / "editor.json").read_text(encoding="utf-8"))
    saved = ctx["client"].patch(ctx["url"], {"version": 1, "content": value}, format="json")
    assert saved.status_code == 200, saved.data
    assert saved.data["content"] == value
    assert "第一项" in saved.data["plain_text"]


def test_ai_context_private_sessions_and_run_permissions(ctx):
    deploy_agent(ctx)
    client, url = ctx["client"], ctx["url"]
    own = client.post(url + "/conversation").data["id"]
    assert client.post(url + "/conversation").data["id"] == own
    response = send(ctx, selection="正文")
    assert response.status_code == 202, response.data
    run = Run.objects.get(pk=response.data["id"])
    assert run.input["document_id"] == ctx["id"]
    assert "正文内容" in run.input["message"] and '"selection": "正文"' in run.input["message"]
    user_message = Message.objects.get(run=run, role="user")
    assert user_message.content == "请润色"
    assert send(ctx, selection="正文").data["id"] == str(run.id)
    assert send(ctx, selection="不存在").status_code == 400
    assert send(ctx, version=999).status_code == 409
    Message.objects.create(conversation_id=own, run=run, role="assistant", content="建议内容")
    detail = client.get(url + "/conversation")
    assert detail.data["messages"][-1]["metadata"]["document_context"]["version"] == 1
    run_root = f"/api/v1/organizations/{ctx['org'].id}/runs/{run.id}"
    share(ctx)
    client.force_authenticate(ctx["reader"])
    theirs = client.post(url + "/conversation").data["id"]
    assert theirs != own
    assert client.get(url + "/conversation").data["messages"] == []
    general_history = client.get("/api/v1/conversations/", HTTP_X_ORGANIZATION_ID=str(ctx["org"].id))
    assert general_history.status_code == 200
    history_items = general_history.data.get("results", []) if isinstance(general_history.data, dict) else general_history.data
    assert theirs not in {str(item["id"]) for item in history_items}
    assert client.get(run_root).status_code == 404
    assert client.get(run_root + "/events").status_code == 404
    assert client.get(f"/api/v1/conversations/{own}/", HTTP_X_ORGANIZATION_ID=str(ctx["org"].id)).status_code == 404
    read_run = send(ctx)
    assert read_run.status_code == 202, read_run.data
    assert client.post(url + f"/runs/{read_run.data['id']}/commands", {"type": "cancel", "idempotency_key": "cancel-doc", "payload": {}}, format="json").status_code == 202
    client.force_authenticate(ctx["owner"])
    client.delete(url + f"/shares?user_id={ctx['reader'].id}")
    client.force_authenticate(ctx["reader"])
    assert send(ctx).status_code == 404
    assert client.get(url + "/conversation").status_code == 404
    assert client.get(run_root.replace(str(run.id), read_run.data['id'])).status_code == 404


def test_ai_rejects_generic_bypass_and_oversize_context(ctx):
    deploy_agent(ctx)
    conversation_id = ctx["client"].post(ctx["url"] + "/conversation").data["id"]
    generic = ctx["client"].post(f"/api/v1/conversations/{conversation_id}/send_message/", {"content": "绕过"}, format="json", HTTP_IDEMPOTENCY_KEY="bypass", HTTP_X_ORGANIZATION_ID=str(ctx["org"].id))
    assert generic.status_code == 400, generic.data
    Document.objects.filter(pk=ctx["id"]).update(plain_text="文" * 60001)
    assert send(ctx).status_code == 400
    assert not Run.objects.filter(input__document_id=ctx["id"]).exists()


def test_deleted_document_hides_run_audit_and_removes_sessions(ctx):
    deploy_agent(ctx)
    ctx["client"].post(ctx["url"] + "/conversation")
    response = send(ctx)
    assert response.status_code == 202, response.data
    assert ctx["client"].delete(ctx["url"]).status_code == 204
    assert not DocumentSession.objects.exists()
    assert not Conversation.objects.filter(title__startswith="在线文档：").exists()
    assert ctx["client"].get(f"/api/v1/organizations/{ctx['org'].id}/runs/{response.data['id']}").status_code == 404


@pytest.mark.django_db
def test_package_sync_is_idempotent(tmp_path, settings):
    shutil.copytree(settings.APP_CENTER_ROOT / "documents", tmp_path / "documents")
    settings.APP_CENTER_ROOT = tmp_path
    owner = get_user_model().objects.create_user(username="doc-install")
    org = owner.owned_organizations.get()
    for _ in range(2):
        call_command("sync_app_center", package_id="documents", organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug="documents")
    assert app.name == "在线文档" and app.category.slug == "productivity" and app.is_active
    assert app.draft.content["renderer_key"] == "documents"
    assert app.revisions.count() == 1 and app.deployments.count() == 1

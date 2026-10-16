import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.applications.models import Application
from apps.enterprise.models import Membership
from modules.execution.models import Run, RunArtifact
from modules.execution.infrastructure.artifacts import get_artifact_storage
from app_center.web_fetch.runtime import execute


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.ROOT_URLCONF = "app_center.web_fetch.backend.tests.urls"
    settings.ARTIFACT_ROOT = tmp_path / "artifacts"
    settings.ARTIFACT_STORAGE_BACKEND = "local"
    owner = get_user_model().objects.create_user(username="fetch-owner")
    other = get_user_model().objects.create_user(username="fetch-other")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role=Membership.Role.ADMIN)
    call_command("sync_app_center", package_id="web-fetch", organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug="web-fetch")
    app.visibility = "organization"
    app.save(update_fields=["visibility"])
    client = APIClient(); client.force_authenticate(owner)
    root = f"/api/v1/organizations/{org.id}"
    return SimpleNamespace(owner=owner, other=other, org=org, app=app, client=client, root=root,
                           url=f"{root}/applications/{app.id}/web-fetch/runs")


def start(ctx, url="https://example.com/article", key="fetch-1", **extra):
    return ctx.client.post(ctx.url, {"url": url, **extra}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_manifest_and_request_idempotency(ctx):
    call_command("sync_app_center", package_id="web-fetch", organization_id=str(ctx.org.id))
    assert ctx.app.revisions.count() == 1
    first = start(ctx)
    assert first.status_code == 201, first.data
    again = start(ctx)
    assert again.status_code == 200 and first.data["id"] == again.data["id"]
    assert first.data["executor_key"] == "web-fetch"
    assert start(ctx, url="https://example.com/other").status_code == 409
    assert start(ctx, key="fetch-2").data["id"] != first.data["id"]
    assert ctx.client.post(ctx.url, {"url": "https://example.com/"}, format="json").status_code == 400
    assert start(ctx, key="unknown", cookie="secret").status_code == 400


@pytest.mark.parametrize("url", ["", "file:///etc/passwd", "ftp://example.com/", "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/", "https://user:pass@example.com/", "http://localhost/", "http://example.com:8080/", "https://example.com\\@127.0.0.1/"])
def test_invalid_urls_are_rejected_before_queueing(ctx, url):
    assert start(ctx, url=url).status_code == 400
    assert not Run.objects.filter(executor_key="web-fetch").exists()


def test_all_run_surfaces_and_artifact_downloads_are_private(ctx):
    run = Run.objects.get(pk=start(ctx).data["id"])
    content = b'{"markdown":"private"}'
    key = f"web-fetch-test/{run.id}.json"
    get_artifact_storage().put(key, content)
    artifact = RunArtifact.objects.create(organization=ctx.org, run=run, kind="web-document", object_key=key,
        content_hash=hashlib.sha256(content).hexdigest(), mime_type="application/json", size=len(content))
    assert ctx.client.get(ctx.url).data["count"] == 1
    access = ctx.client.get(f"{ctx.root}/runs/{run.id}/artifacts/{artifact.id}/access")
    assert access.status_code == 200
    response = ctx.client.get(access.data["url"])
    assert b"".join(response.streaming_content) == content
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(ctx.url).data["count"] == 0
    assert ctx.client.get(ctx.url + f"/{run.id}").status_code == 404
    assert ctx.client.get(access.data["url"]).status_code == 404
    for suffix in ["", "/events", "/stream", "/artifacts", f"/artifacts/{artifact.id}/access"]:
        assert ctx.client.get(f"{ctx.root}/runs/{run.id}{suffix}").status_code == 404
    assert ctx.client.post(f"{ctx.root}/runs/{run.id}/commands", {"type": "cancel", "idempotency_key": "no-access"}, format="json").status_code == 404
    other_org = ctx.other.owned_organizations.get()
    assert ctx.client.get(ctx.url.replace(str(ctx.org.id), str(other_org.id))).status_code == 404
    ctx.client.force_authenticate(None)
    assert ctx.client.get(access.data["url"]).status_code in {403, 404}
    ctx.client.force_authenticate(ctx.owner)
    ctx.app.is_active = False; ctx.app.save(update_fields=["is_active"])
    assert ctx.client.get(f"{ctx.root}/runs/{run.id}").status_code == 404


class Sink:
    cancelled = False

    def __init__(self):
        self.artifacts = []; self.events = []

    def emit(self, kind, value):
        self.events.append((kind, value))

    def create_artifact(self, **value):
        self.artifacts.append(value)


def test_execution_persists_markdown_and_json_without_large_summary(ctx):
    run = Run.objects.get(pk=start(ctx).data["id"])
    document = {"version": 1, "title": "测试", "url": run.input["url"], "markdown": "# 测试\n\n正文",
                "media": [], "warnings": [], "adapter": "generic", "extractionMethod": "defuddle"}
    sink = Sink()
    with patch("app_center.web_fetch.runtime.run_engine", return_value=document):
        result = execute({"run_id": str(run.id), "organization_id": str(ctx.org.id), "input": run.input}, sink)
    assert result["title"] == "测试" and "markdown" not in result
    assert [a["filename"] for a in sink.artifacts] == ["article.md", "article.json"]
    assert json.loads(sink.artifacts[1]["content"]) == document


def test_cancel_before_start_and_after_extraction_does_not_publish(ctx):
    sink = Sink(); sink.cancelled = True
    with patch("app_center.web_fetch.runtime.run_engine") as engine:
        assert execute({}, sink) == {}
    engine.assert_not_called()
    run = Run.objects.get(pk=start(ctx).data["id"])
    sink.cancelled = False
    def cancel(*args):
        sink.cancelled = True
        return {"markdown": "body"}
    with patch("app_center.web_fetch.runtime.run_engine", side_effect=cancel):
        assert execute({"run_id": str(run.id), "organization_id": str(ctx.org.id), "input": run.input}, sink) == {}
    assert sink.artifacts == []

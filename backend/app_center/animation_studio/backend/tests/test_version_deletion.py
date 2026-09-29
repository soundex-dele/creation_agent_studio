import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from modules.execution.models import Run
from ..access import generation_for
from ..models import AnimationProject, AnimationVersion
from ..projects import import_history
from .test_animation import ctx, generate, ready, export
from .test_studio import create


def imported_version(ctx):
    run = ready(ctx)
    import_history(ctx.user, ctx.app)
    return AnimationVersion.objects.get(run=run)


def url(ctx, version, project_id=None):
    return f"{ctx.url}/projects/{project_id or version.project_id}/versions/{version.id}"


def test_delete_hides_version_without_reimporting_or_losing_draft_and_files(ctx):
    version = imported_version(ctx)
    project = version.project
    original_draft = project.draft
    artifacts = list(version.run.artifacts.values_list("id", flat=True))
    assert ctx.client.delete(url(ctx, version)).status_code == 204
    assert ctx.client.delete(url(ctx, version)).status_code == 204
    version.refresh_from_db()
    assert version.deleted_at is not None
    project.refresh_from_db()
    assert project.draft == original_draft and project.revision == 1
    assert list(version.run.artifacts.values_list("id", flat=True)) == artifacts
    assert ctx.client.get(f"{ctx.url}/projects/{project.id}").data["versions"] == []
    assert ctx.client.get(ctx.url + "/generations").data["count"] == 0
    assert ctx.client.get(f"{ctx.url}/generations/{version.run_id}").status_code == 404
    assert export(ctx, version.run).status_code == 404
    assert ctx.client.post(f"{ctx.url}/projects/{project.id}/restore", {
        "version_id": str(version.id), "revision": 1,
    }, format="json").status_code == 404
    # Existing render/conversion dependencies still have access to their source.
    assert generation_for(ctx.user, ctx.app, version.run_id, ready=True, include_deleted=True).id == version.run_id
    for _ in range(2):
        assert ctx.client.get(ctx.url + "/projects").data["count"] == 1
        assert ctx.client.get(f"{ctx.url}/projects/{project.id}").data["versions"] == []
    assert AnimationVersion.objects.count() == 1


def test_delete_keeps_other_versions_and_history_chain(ctx):
    version = imported_version(ctx)
    child = generate(ctx, key="child", source_run_id=str(version.run_id))
    assert child.status_code == 201
    import_history(ctx.user, ctx.app)
    assert ctx.client.delete(url(ctx, version)).status_code == 204
    import_history(ctx.user, ctx.app)
    project = ctx.client.get(f"{ctx.url}/projects/{version.project_id}").data
    assert [v["run"]["id"] for v in project["versions"]] == [child.data["id"]]
    assert AnimationProject.objects.count() == 1


@pytest.mark.parametrize("status", ["queued", "running", "waiting_input", "waiting_children", "cancelling"])
def test_delete_rejects_active_generation(ctx, status):
    version = imported_version(ctx)
    pending = {"pending_input_request_id": uuid.uuid4(), "pending_input_kind": "answer",
        "pending_input_expires_at": timezone.now() + timedelta(minutes=5)} if status == "waiting_input" else {}
    Run.objects.filter(pk=version.run_id).update(status=status, **pending)
    response = ctx.client.delete(url(ctx, version))
    assert response.status_code == 409 and "生成" in response.data["detail"]
    version.refresh_from_db()
    assert version.deleted_at is None


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_delete_allows_terminal_generation(ctx, status):
    version = imported_version(ctx)
    Run.objects.filter(pk=version.run_id).update(status=status)
    assert ctx.client.delete(url(ctx, version)).status_code == 204


def test_delete_waits_for_export_to_finish(ctx):
    version = imported_version(ctx)
    result = export(ctx, version.run)
    assert result.status_code == 201
    assert ctx.client.delete(url(ctx, version)).status_code == 409
    Run.objects.filter(pk=result.data["id"]).update(status="cancelled")
    assert ctx.client.delete(url(ctx, version)).status_code == 204


def test_delete_checks_owner_project_and_tenant(ctx):
    version = imported_version(ctx)
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.delete(url(ctx, version)).status_code == 404
    ctx.client.force_authenticate(ctx.user)
    other_project = create(ctx)
    assert ctx.client.delete(url(ctx, version, other_project["id"])).status_code == 404
    other_org = ctx.other.owned_organizations.get()
    foreign_url = url(ctx, version).replace(str(ctx.org.id), str(other_org.id))
    assert ctx.client.delete(foreign_url).status_code in (403, 404)
    version.refresh_from_db()
    assert version.deleted_at is None


def test_copied_legacy_project_cannot_delete_its_source_version(ctx):
    version = imported_version(ctx)
    copied = ctx.client.post(f"{ctx.url}/projects/{version.project_id}/copy", {}, format="json")
    assert copied.status_code == 201
    detail = ctx.client.get(f"{ctx.url}/projects/{copied.data['id']}").data
    assert detail["versions"][0]["can_delete"] is False
    assert ctx.client.delete(url(ctx, version, copied.data["id"])).status_code == 404
    assert ctx.client.get(f"{ctx.url}/projects/{version.project_id}").data["versions"][0]["can_delete"] is True


def test_delete_last_structured_version_keeps_editable_draft_and_allows_new_generation(ctx):
    project = create(ctx)
    tasks_url = f"{ctx.url}/projects/{project['id']}/tasks"
    body = {"action": "generate", "revision": project["revision"]}
    first = ctx.client.post(tasks_url, body, format="json", HTTP_IDEMPOTENCY_KEY="first-version")
    assert first.status_code == 201
    Run.objects.filter(pk=first.data["id"]).update(status="failed")
    version = AnimationVersion.objects.get(run_id=first.data["id"])
    assert ctx.client.delete(url(ctx, version)).status_code == 204
    ctx.client.get(ctx.url + "/projects")
    detail = ctx.client.get(f"{ctx.url}/projects/{project['id']}").data
    assert detail["versions"] == [] and detail["draft"] == project["draft"]
    second = ctx.client.post(tasks_url, body, format="json", HTTP_IDEMPOTENCY_KEY="second-version")
    assert second.status_code == 201
    detail = ctx.client.get(f"{ctx.url}/projects/{project['id']}").data
    assert [v["run"]["id"] for v in detail["versions"]] == [second.data["id"]]

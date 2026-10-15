from datetime import timedelta
import os
from pathlib import Path
import subprocess
import time

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from .. import filesystem as fs
from .. import worker
from ..models import CleanerEntry, CleanerPreview, CleanerResult, CleanerTask

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows handle and fixed-volume integration tests")


@pytest.fixture
def ctx(db, tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "close_old_connections", lambda: None)
    user = get_user_model().objects.create_user(username="cleaner-admin", role="admin")
    org = user.owned_organizations.get()
    category = ApplicationCategory.objects.create(name="清理", slug="cleaner-test")
    app = Application.objects.create(organization=org, category=category, name="磁盘清理大师", slug="disk-cleaner",
                                     created_by=user, kind="custom", visibility="organization")
    client = APIClient()
    client.force_authenticate(user)
    root = f"/api/v1/organizations/{org.id}/applications/{app.pk}/disk-cleaner"
    folder = tmp_path / "files"
    folder.mkdir()
    return dict(client=client, root=root, user=user, org=org, app=app, folder=folder)


def post(ctx, path, data, status=201):
    response = ctx["client"].post(ctx["root"] + path, data, format="json")
    assert response.status_code == status, response.data
    return response.data


def scan(ctx, mode="large", key="scan", root=None):
    return post(ctx, "/tasks", {"request_key": key, "mode": mode, "root": str(root or ctx["folder"]), "minimum_bytes": 1})


def execute():
    assert worker.process_next(fs.host_id())


def prepare(ctx):
    task = scan(ctx)
    execute()
    saved = CleanerTask.objects.get(pk=task["id"])
    assert saved.state == "completed", saved.message
    ids = [str(pk) for pk in saved.entries.values_list("id", flat=True)]
    preview = post(ctx, "/previews", {"scan_id": task["id"], "entry_ids": ids})
    return saved, preview


@pytest.mark.django_db(transaction=True)
def test_real_handle_delete_and_exact_results(ctx):
    file = ctx["folder"] / "废弃.bin"
    file.write_bytes(b"abc123")
    task, preview = prepare(ctx)
    assert file.exists()  # scan + preview are strictly read-only
    detail = ctx["client"].get(ctx["root"] + f"/previews/{preview['id']}")
    assert detail.data["results"][0]["path"] == str(file)
    cleanup = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    execute()
    result = CleanerTask.objects.get(pk=cleanup["id"])
    assert result.state == "completed", result.message
    outcome = result.results.get()
    assert outcome.state == "deleted", outcome.reason
    assert not file.exists()
    assert ctx["folder"].exists()
    assert result.deleted_bytes == 6
    assert result.free_before and result.free_after
    assert post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]}, 200)["id"] == cleanup["id"]
    assert not worker.process_next(fs.host_id())


def test_admin_and_application_boundary(ctx):
    member = get_user_model().objects.create_user(username="cleaner-member")
    ctx["client"].force_authenticate(member)
    assert ctx["client"].get(ctx["root"] + "/host").status_code == 403
    ctx["client"].force_authenticate(ctx["user"])
    ctx["app"].is_active = False
    ctx["app"].save()
    assert ctx["client"].get(ctx["root"] + "/host").status_code == 404


def test_scan_idempotency_and_different_payload(ctx):
    values = {"request_key": "stable", "mode": "large", "root": str(ctx["folder"]), "minimum_bytes": 1}
    first = post(ctx, "/tasks", values)
    assert post(ctx, "/tasks", values, 200)["id"] == first["id"]
    post(ctx, "/tasks", {**values, "minimum_bytes": 2}, 400)
    assert post(ctx, "/tasks", {**values, "request_key": "new"})["id"] != first["id"]


def test_analysis_aggregates_and_never_cleanable(ctx):
    child = ctx["folder"] / "child"
    child.mkdir()
    (child / "a").write_bytes(b"123")
    (ctx["folder"] / "b").write_bytes(b"12")
    task = scan(ctx, mode="analysis")
    execute()
    saved = CleanerTask.objects.get(pk=task["id"])
    assert saved.total_bytes == 5 and saved.processed == 2
    rows = ctx["client"].get(ctx["root"] + f"/tasks/{saved.pk}/entries").data
    assert rows["count"] == 2
    directory = next(row for row in rows["results"] if row["kind"] == "directory")
    assert directory["size"] == 3
    nested = ctx["client"].get(ctx["root"] + f"/tasks/{saved.pk}/entries", {"parent": str(child)}).data
    assert nested["count"] == 1
    post(ctx, "/previews", {"scan_id": str(saved.pk), "entry_ids": [nested["results"][0]["id"]]}, 400)


def test_preview_expiry_tampering_and_other_scan(ctx):
    (ctx["folder"] / "a").write_bytes(b"123")
    task, preview = prepare(ctx)
    post(ctx, "/cleanups", {"request_key": "bad", "token": preview["token"] + "tampered"}, 400)
    CleanerPreview.objects.filter(pk=preview["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    post(ctx, "/cleanups", {"request_key": "expired", "token": preview["token"]}, 400)
    other = scan(ctx, key="other")
    execute()
    post(ctx, "/previews", {"scan_id": other["id"], "entry_ids": [str(task.entries.first().pk)]}, 400)


def test_file_replaced_modified_missing_locked_and_success(ctx):
    for name in ["replaced", "modified", "missing", "locked", "ok"]:
        (ctx["folder"] / name).write_bytes(b"abc")
    _, preview = prepare(ctx)
    (ctx["folder"] / "replaced").unlink()
    (ctx["folder"] / "replaced").write_bytes(b"new")
    (ctx["folder"] / "modified").write_bytes(b"changed")
    (ctx["folder"] / "missing").unlink()
    task = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    with fs.handle(ctx["folder"] / "locked", deleting=True):
        execute()
    results = CleanerResult.objects.filter(task_id=task["id"])
    assert results.filter(state="deleted").count() == 1, list(results.values("state", "reason"))
    assert results.exclude(state="deleted").count() == 4
    assert (ctx["folder"] / "modified").exists()


def test_cancel_and_host_binding(ctx):
    (ctx["folder"] / "a").write_bytes(b"abc")
    task = scan(ctx)
    assert not worker.process_next("another-machine")
    post(ctx, f"/tasks/{task['id']}", {}, 200)
    execute()
    assert CleanerTask.objects.get(pk=task["id"]).state == "cancelled"
    assert (ctx["folder"] / "a").exists()


def test_interruption_never_retries_uncertain_delete(ctx):
    (ctx["folder"] / "a").write_bytes(b"abc")
    _, preview = prepare(ctx)
    task = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    CleanerTask.objects.filter(pk=task["id"]).update(state="running")
    CleanerResult.objects.filter(task_id=task["id"]).update(state="deleting")
    worker.interrupt_previous(fs.host_id())
    assert CleanerTask.objects.get(pk=task["id"]).state == "interrupted"
    assert CleanerResult.objects.get(task_id=task["id"]).state == "unknown"
    assert not worker.process_next(fs.host_id())
    assert (ctx["folder"] / "a").exists()


def test_cache_age_filter_and_protected_directory(ctx, monkeypatch):
    monkeypatch.setattr(fs, "cache_roots", lambda: [str(ctx["folder"])])
    old = ctx["folder"] / "old"
    old.write_bytes(b"old")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    (ctx["folder"] / "recent").write_bytes(b"new")
    task = scan(ctx, mode="cache")
    execute()
    assert list(CleanerEntry.objects.filter(task_id=task["id"]).values_list("path", flat=True)) == [str(old)]
    monkeypatch.setattr(fs, "protected_roots", lambda: [ctx["folder"]])
    post(ctx, "/tasks", {"request_key": "protected", "mode": "large", "root": str(ctx["folder"])}, 400)


def test_root_path_and_escape_protections(ctx):
    root = ctx["folder"]
    for value in [str(Path(root.anchor)), r"\\server\share", str(root / "file:stream")]:
        post(ctx, "/tasks", {"request_key": value, "mode": "large", "root": value}, 400)
    outside = root.parent / "outside"
    outside.write_bytes(b"safe")
    with pytest.raises(fs.UnsafePath):
        fs.delete_verified(str(outside), str(root), fs.snapshot(outside), fs.snapshot(root), "large")
    assert outside.exists()


def test_junction_is_not_scanned_or_deleted(ctx):
    outside = ctx["folder"].parent / "outside"
    outside.mkdir()
    victim = outside / "victim"
    victim.write_bytes(b"preserve")
    junction = ctx["folder"] / "junction"
    # Creation only; deletion below uses rmdir on this exact verified junction, never recursively.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True)
    try:
        task = scan(ctx)
        execute()
        assert not CleanerEntry.objects.filter(task_id=task["id"]).exists()
        with pytest.raises(fs.UnsafePath):
            fs.validate_root(str(junction), "large")
        assert victim.exists()
    finally:
        assert junction.parent == ctx["folder"] and junction.is_junction()
        junction.rmdir()


def test_revoked_permission_stops_queued_cleanup(ctx):
    file = ctx["folder"] / "a"
    file.write_bytes(b"123")
    _, preview = prepare(ctx)
    task = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    ctx["user"].role = "member"
    ctx["user"].save()
    execute()
    assert CleanerTask.objects.get(pk=task["id"]).state == "failed"
    assert file.exists()


def test_host_capabilities_and_unsupported(ctx, monkeypatch):
    worker.heartbeat(fs.host_id())
    response = ctx["client"].get(ctx["root"] + "/host")
    assert response.data["worker_online"] and response.data["volumes"]
    monkeypatch.setattr(fs, "supported", lambda: False)
    assert not ctx["client"].get(ctx["root"] + "/host").data["supported"]
    post(ctx, "/tasks", {"request_key": "unsupported", "mode": "large", "root": str(ctx["folder"])}, 400)


def test_expired_queued_cleanup_does_not_execute(ctx):
    file = ctx["folder"] / "a"
    file.write_bytes(b"123")
    _, preview = prepare(ctx)
    task = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    CleanerPreview.objects.filter(pk=preview["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    execute()
    assert CleanerTask.objects.get(pk=task["id"]).state == "failed"
    assert file.exists()


def test_pagination_sort_and_browse(ctx):
    for index in range(53):
        (ctx["folder"] / f"file-{index:02d}").write_bytes(b"a" * (index + 1))
    subdirectory = ctx["folder"] / "目录"
    subdirectory.mkdir()
    task = scan(ctx)
    execute()
    path = ctx["root"] + f"/tasks/{task['id']}/entries"
    first = ctx["client"].get(path, {"sort": "-size"}).data
    assert first["count"] == 53 and len(first["results"]) == 50
    assert first["results"][0]["size"] == 53
    second = ctx["client"].get(path, {"page": 2}).data
    assert len(second["results"]) == 3
    assert ctx["client"].get(path, {"sort": "identity"}).status_code == 400
    directories = ctx["client"].get(ctx["root"] + "/directories", {"path": str(ctx["folder"])}).data
    assert directories["directories"] == [{"path": str(subdirectory), "name": "目录"}]


def test_task_data_is_isolated_by_owner_application_organization_and_host(ctx):
    task = scan(ctx)
    instance = CleanerTask.objects.get(pk=task["id"])
    other = get_user_model().objects.create_user(username="second-admin", role="admin")
    for field, value in [("owner_id", other.pk), ("organization_id", other.owned_organizations.get().id), ("host", "other-host")]:
        original = getattr(instance, field)
        CleanerTask.objects.filter(pk=instance.pk).update(**{field: value})
        assert ctx["client"].get(ctx["root"] + f"/tasks/{instance.pk}").status_code == 404
        assert ctx["client"].get(ctx["root"] + "/tasks").data["count"] == 0
        CleanerTask.objects.filter(pk=instance.pk).update(**{field: original})
    other_app = Application.objects.create(organization=ctx["org"], category=ctx["app"].category, name="另一应用",
        slug="other-cleaner", created_by=ctx["user"], kind="custom", visibility="organization")
    CleanerTask.objects.filter(pk=instance.pk).update(application=other_app)
    assert ctx["client"].get(ctx["root"] + f"/tasks/{instance.pk}").status_code == 404


def test_single_tenant_api_alias(ctx, settings):
    settings.SINGLE_TENANT_MODE = True
    settings.SINGLE_TENANT_ORGANIZATION_ID = str(ctx["org"].id)
    response = ctx["client"].get(f"/api/v1/applications/{ctx['app'].pk}/disk-cleaner/host")
    assert response.status_code == 200, response.data


def test_hardlinks_and_root_replacement_are_rejected(ctx):
    file = ctx["folder"] / "a"
    file.write_bytes(b"123")
    os.link(file, ctx["folder"] / "hardlink")
    task = scan(ctx)
    execute()
    assert not CleanerEntry.objects.filter(task_id=task["id"]).exists()
    (ctx["folder"] / "hardlink").unlink()
    root_identity = fs.snapshot(ctx["folder"])
    file_identity = fs.snapshot(file)
    # Altering the saved directory identity simulates a replacement root.
    with pytest.raises(fs.UnsafePath, match="扫描目录已经替换"):
        fs.delete_verified(file, ctx["folder"], file_identity, {**root_identity, "index": -1}, "large")
    assert file.exists()


def test_cancel_during_cleanup_keeps_remaining_files(ctx, monkeypatch):
    for name in ["a", "b"]:
        (ctx["folder"] / name).write_bytes(b"123")
    _, preview = prepare(ctx)
    task = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    real_delete = fs.delete_verified
    def delete_one(*args):
        real_delete(*args)
        CleanerTask.objects.filter(pk=task["id"]).update(cancel_requested=True)
    monkeypatch.setattr(fs, "delete_verified", delete_one)
    execute()
    saved = CleanerTask.objects.get(pk=task["id"])
    assert saved.state == "cancelled"
    assert saved.deleted_bytes == 3
    assert saved.results.filter(state="deleted").count() == 1
    assert len(list(ctx["folder"].iterdir())) == 1


def test_protection_is_rechecked_after_preview(ctx, monkeypatch):
    file = ctx["folder"] / "a"
    file.write_bytes(b"123")
    _, preview = prepare(ctx)
    task = post(ctx, "/cleanups", {"request_key": "delete", "token": preview["token"]})
    monkeypatch.setattr(fs, "protected_roots", lambda: [ctx["folder"]])
    execute()
    assert CleanerTask.objects.get(pk=task["id"]).results.get().state == "skipped"
    assert file.exists()

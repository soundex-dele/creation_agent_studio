import asyncio
import hashlib
import os
import tracemalloc
from io import BytesIO
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.handlers.asgi import ASGIRequest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from .. import services
from ..media import ContentView, stream_file_async
from ..models import DriveChunk, DriveEntry, DriveSpace, DriveUpload
from ..storage import object_path, upload_key


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.MY_DRIVE_ROOT = tmp_path / "drive"
    settings.MY_DRIVE_CHUNK_BYTES = 4
    settings.MY_DRIVE_X_ACCEL_REDIRECT = False
    owner = get_user_model().objects.create_user(username="drive-owner")
    reader = get_user_model().objects.create_user(username="drive-reader")
    outsider = get_user_model().objects.create_user(username="drive-outsider")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=reader, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name="网盘", slug="drive-test")
    app = Application.objects.create(organization=org, category=category, name="我的网盘", slug="my-drive",
        created_by=owner, kind="custom", visibility="organization")
    client = APIClient()
    client.force_authenticate(owner)
    root = f"/api/v1/organizations/{org.id}/applications/{app.pk}/my-drive"
    return dict(client=client, root=root, owner=owner, reader=reader, outsider=outsider, org=org, app=app)


def post(ctx, tail, data=None, expected=200):
    response = ctx["client"].post(ctx["root"] + tail, data or {}, format="json")
    assert response.status_code == expected, getattr(response, "data", None)
    return response.data


def folder(ctx, name="目录", parent=None):
    return post(ctx, "", {"name": name, "parent": parent}, 201)


def upload(ctx, content=b"abcdefgh", name="video.mp4", parent=None):
    value = post(ctx, "/uploads", {"name": name, "size": len(content), "parent": parent}, 201)
    for offset in range(0, len(content), 4):
        assert chunk(ctx, value["id"], content[offset:offset + 4], offset).status_code == 200
    return post(ctx, f"/uploads/{value['id']}/complete")


def chunk(ctx, pk, content, offset=0, digest=None):
    return ctx["client"].put(ctx["root"] + f"/uploads/{pk}/chunk", content,
        content_type="application/octet-stream", HTTP_X_CHUNK_OFFSET=str(offset),
        HTTP_X_CHUNK_SHA256=digest or hashlib.sha256(content).hexdigest())


def act(ctx, action, ids, **extra):
    return post(ctx, "/actions", dict(action=action, ids=ids, **extra))


def content_url(ctx, entry, mode="download"):
    token = post(ctx, f"/entries/{entry}/access", {"mode": mode})["token"]
    return ctx["root"] + "/content?token=" + token


def test_folders_search_move_conflict_and_trash(ctx):
    a = folder(ctx)
    b = folder(ctx)
    assert b["name"] == "目录 (1)"
    child = folder(ctx, "子目录", a["id"])
    file = upload(ctx, name="素材.mp4", parent=child["id"])["entry"]
    root = ctx["root"]
    assert ctx["client"].get(root, {"search": "素材", "type": "video"}).data["count"] == 1
    assert len(ctx["client"].get(root, {"parent": child["id"]}).data["breadcrumbs"]) == 2
    post(ctx, "/actions", {"action": "move", "ids": [a["id"]], "parent": child["id"]}, 400)
    act(ctx, "trash", [a["id"], child["id"], file])
    assert ctx["client"].get(root, {"scope": "trash"}).data["count"] == 1
    assert ctx["client"].get(root, {"search": "素材"}).data["count"] == 0
    folder(ctx)
    act(ctx, "restore", [a["id"]])
    assert DriveEntry.objects.get(pk=a["id"]).name == "目录 (2)"
    assert not DriveEntry.objects.get(pk=file).trash_batch
    act(ctx, "move", [child["id"]], parent=b["id"])
    assert str(DriveEntry.objects.get(pk=child["id"]).parent_id) == b["id"]


def test_restore_missing_parent_and_separate_trash_batches(ctx):
    a = folder(ctx)
    b = folder(ctx, "inner", a["id"])
    act(ctx, "trash", [b["id"]])
    act(ctx, "trash", [a["id"]])
    act(ctx, "restore", [b["id"]])
    assert DriveEntry.objects.get(pk=b["id"]).parent_id is None


def test_upload_idempotency_and_resume_manifest(ctx):
    value = post(ctx, "/uploads", {"name": "a.bin", "size": 6}, 201)
    pk = value["id"]
    assert chunk(ctx, pk, b"abcd").status_code == 200
    assert chunk(ctx, pk, b"abcd").data["offset"] == 4
    assert chunk(ctx, pk, b"xxxx").status_code == 409
    assert chunk(ctx, pk, b"ef", 5).status_code == 409
    assert chunk(ctx, pk, b"e", 4).status_code == 400
    assert chunk(ctx, pk, b"ef", 4, "0" * 64).status_code == 400
    detail = ctx["client"].get(ctx["root"] + f"/uploads/{pk}").data
    assert detail["offset"] == 4 and len(detail["chunks"]) == 1
    post(ctx, f"/uploads/{pk}/complete", expected=409)
    assert chunk(ctx, pk, b"ef", 4).status_code == 200
    completed = post(ctx, f"/uploads/{pk}/complete")
    assert post(ctx, f"/uploads/{pk}/complete")["entry"] == completed["entry"]
    entry = DriveEntry.objects.get(pk=completed["entry"])
    assert object_path(entry.object_key).read_bytes() == b"abcdef"
    assert chunk(ctx, pk, b"abcd").status_code == 409


def test_zero_size_and_name_validation(ctx):
    assert upload(ctx, b"")["state"] == "completed"
    for name in ["..", "a/b", "a\\b", "a\x01b"]:
        post(ctx, "", {"name": name}, 400)


def test_privacy_and_membership_revocation(ctx):
    value = upload(ctx)
    url = content_url(ctx, value["entry"])
    client = ctx["client"]
    client.force_authenticate(ctx["reader"])
    assert client.get(ctx["root"]).data["count"] == 0
    assert client.get(ctx["root"] + f"/uploads/{value['id']}").status_code == 404
    post(ctx, f"/entries/{value['entry']}/access", expected=404)
    client.force_authenticate(ctx["outsider"])
    assert client.get(ctx["root"]).status_code == 403
    Membership.objects.filter(user=ctx["owner"], organization=ctx["org"]).update(is_active=False)
    assert client.get(url).status_code == 403


def test_disabled_application_rejects_signed_content(ctx):
    value = upload(ctx)
    url = content_url(ctx, value["entry"])
    ctx["app"].is_active = False
    ctx["app"].save(update_fields=["is_active"])
    assert ctx["client"].get(url).status_code == 404
    assert ctx["client"].get(ctx["root"]).status_code == 404


def test_single_tenant_alias_and_cross_org_token(ctx, settings):
    value = upload(ctx)
    url = content_url(ctx, value["entry"])
    other_org = ctx["outsider"].owned_organizations.get()
    assert ctx["client"].get(url.replace(str(ctx["org"].id), str(other_org.id))).status_code == 403
    settings.SINGLE_TENANT_MODE = True
    settings.SINGLE_TENANT_ORGANIZATION_ID = str(ctx["org"].id)
    alias = f"/api/v1/applications/{ctx['app'].pk}/my-drive"
    assert ctx["client"].get(alias).status_code == 200
    assert ctx["client"].get(url.replace(f"/organizations/{ctx['org'].id}", "")).status_code == 200


def test_ranges_head_and_credentials(ctx):
    value = upload(ctx)
    url = content_url(ctx, value["entry"], "preview")
    client = ctx["client"]
    response = client.get(url, HTTP_RANGE="bytes=2-5")
    assert response.status_code == 206 and response["Content-Range"] == "bytes 2-5/8"
    assert b"".join(response.streaming_content) == b"cdef"
    assert b"".join(client.get(url, HTTP_RANGE="bytes=-2").streaming_content) == b"gh"
    assert client.head(url)["Content-Length"] == "8"
    assert client.head(url, HTTP_RANGE="bytes=4-")["Content-Length"] == "4"
    for header in ["bytes=8-9", "bytes=3-2", "bytes=-0", "bytes=0-1,4-5"]:
        response = client.get(url, HTTP_RANGE=header)
        assert response.status_code == 416 and response["Content-Range"] == "bytes */8"
    assert client.get(url + "tampered").status_code == 403
    with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 7200):
        assert client.get(url).status_code == 403
    act(ctx, "trash", [value["entry"]])
    assert client.get(url).status_code == 404


def test_preview_allowlist_and_text_limit(ctx, settings):
    for name in ["page.html", "picture.svg", "office.docx"]:
        value = upload(ctx, b"data", name)
        post(ctx, f"/entries/{value['entry']}/access", {"mode": "preview"}, 400)
    settings.MY_DRIVE_CHUNK_BYTES = 2 * 1024 ** 2
    value = post(ctx, "/uploads", {"name": "text.txt", "size": 2 * 1024 ** 2}, 201)
    assert chunk(ctx, value["id"], b"x" * (2 * 1024 ** 2)).status_code == 200
    completed = post(ctx, f"/uploads/{value['id']}/complete")
    response = ctx["client"].get(content_url(ctx, completed["entry"], "preview"))
    assert response["Content-Length"] == str(1024 ** 2)
    assert len(b"".join(response.streaming_content)) == 1024 ** 2


def test_nginx_protected_path(ctx, settings):
    value = upload(ctx)
    settings.MY_DRIVE_X_ACCEL_REDIRECT = True
    response = ctx["client"].get(content_url(ctx, value["entry"]))
    assert response["X-Accel-Redirect"].startswith("/_protected_drive/")
    assert "attachment" in response["Content-Disposition"]


def test_asgi_media_response_is_not_materialized(ctx):
    value = upload(ctx)
    token = post(ctx, f"/entries/{value['entry']}/access")["token"]
    request = ASGIRequest({"type": "http", "method": "GET", "path": ctx["root"] + "/content",
        "query_string": ("token=" + token).encode(), "headers": [], "server": ("testserver", 80)}, BytesIO())
    response = ContentView.as_view()(request, organization_id=ctx["org"].id, application_id=ctx["app"].pk)
    assert response.is_async
    async def consume():
        return b"".join([part async for part in response.streaming_content])
    assert asyncio.run(consume()) == b"abcdefgh"


def test_restore_multiple_separate_batches_preserves_tree(ctx):
    parent = folder(ctx)
    child = folder(ctx, "child", parent["id"])
    act(ctx, "trash", [child["id"]])
    act(ctx, "trash", [parent["id"]])
    act(ctx, "restore", [child["id"], parent["id"]])
    assert not DriveEntry.objects.exclude(trash_batch=None).exists()
    assert str(DriveEntry.objects.get(pk=child["id"]).parent_id) == parent["id"]


def test_quota_reservations_and_cleanup_retry(ctx, settings, monkeypatch):
    settings.MY_DRIVE_QUOTA_BYTES = 10
    settings.MY_DRIVE_MAX_FILE_BYTES = 9
    post(ctx, "/uploads", {"name": "too-big", "size": 10}, 400)
    value = upload(ctx)
    post(ctx, "/uploads", {"name": "overflow", "size": 4}, 400)
    act(ctx, "trash", [value["entry"]])
    assert ctx["client"].get(ctx["root"]).data["capacity"]["used"] == 8
    act(ctx, "purge", [value["entry"]])
    from pathlib import Path
    with monkeypatch.context() as m:
        m.setattr(Path, "unlink", lambda *a, **kw: (_ for _ in ()).throw(OSError("busy")))
        call_command("maintain_my_drive")
    assert DriveEntry.objects.filter(pk=value["entry"]).exists()
    call_command("maintain_my_drive")
    assert not DriveEntry.objects.filter(pk=value["entry"]).exists()
    reserved = post(ctx, "/uploads", {"name": "pending", "size": 8}, 201)
    assert ctx["client"].get(ctx["root"]).data["capacity"]["reserved"] == 8
    assert ctx["client"].delete(ctx["root"] + f"/uploads/{reserved['id']}").status_code == 200
    assert ctx["client"].get(ctx["root"]).data["capacity"]["reserved"] == 8
    call_command("maintain_my_drive")
    assert ctx["client"].get(ctx["root"]).data["capacity"]["reserved"] == 0


def test_expired_upload_cleanup(ctx):
    value = post(ctx, "/uploads", {"name": "abandoned", "size": 8}, 201)
    chunk(ctx, value["id"], b"abcd")
    record = DriveUpload.objects.get(pk=value["id"])
    temporary = object_path(upload_key(record, True))
    DriveUpload.objects.filter(pk=record.pk).update(updated_at=timezone.now() - timedelta(days=8))
    call_command("maintain_my_drive")
    assert not temporary.exists()
    record.refresh_from_db()
    assert record.state == "cancelled"


def test_chunk_database_rollback_discards_unconfirmed_tail(ctx):
    value = post(ctx, "/uploads", {"name": "retry", "size": 8}, 201)
    record = DriveUpload.objects.get(pk=value["id"])
    with patch.object(DriveChunk.objects, "create", side_effect=RuntimeError("DB unavailable")):
        with pytest.raises(RuntimeError):
            services.write_chunk(record.space, ctx["app"], record.pk, 0, hashlib.sha256(b"abcd").hexdigest(), b"abcd")
    record.refresh_from_db()
    assert record.offset == 0
    assert chunk(ctx, record.pk, b"wxyz").status_code == 200
    assert object_path(upload_key(record, True)).read_bytes() == b"wxyz"


def test_finalize_database_failure_recovers_without_copy(ctx):
    value = post(ctx, "/uploads", {"name": "retry", "size": 4}, 201)
    chunk(ctx, value["id"], b"abcd")
    record = DriveUpload.objects.get(pk=value["id"])
    with patch.object(DriveUpload, "save", side_effect=RuntimeError("DB unavailable")):
        with pytest.raises(RuntimeError):
            services.complete_upload(record.space, ctx["app"], record.pk)
    assert object_path(upload_key(record)).exists()
    assert not DriveEntry.objects.filter(kind="file").exists()
    completed = post(ctx, f"/uploads/{record.pk}/complete")
    assert completed["state"] == "completed"
    assert DriveEntry.objects.filter(kind="file").count() == 1


def test_disk_failure_does_not_advance_progress(ctx):
    value = post(ctx, "/uploads", {"name": "retry", "size": 4}, 201)
    with patch("os.fsync", side_effect=OSError("disk full")):
        assert chunk(ctx, value["id"], b"abcd").status_code == 507
    assert DriveUpload.objects.get(pk=value["id"]).offset == 0
    assert chunk(ctx, value["id"], b"abcd").status_code == 200


def test_sparse_file_over_two_gib_has_bounded_memory(ctx):
    size = 3 * 1024 ** 3 + 4
    value = post(ctx, "/uploads", {"name": "large.mp4", "size": size}, 201)
    record = DriveUpload.objects.get(pk=value["id"])
    path = object_path(upload_key(record, True))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        if os.name == "nt":
            import ctypes
            import msvcrt
            returned = ctypes.c_ulong()
            assert ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno())),
                0x900C4, None, 0, None, 0, ctypes.byref(returned), None)
        handle.truncate(size - 4)
    DriveUpload.objects.filter(pk=record.pk).update(offset=size - 4)
    assert chunk(ctx, value["id"], b"tail", size - 4).status_code == 200
    completed = post(ctx, f"/uploads/{record.pk}/complete")
    response = ctx["client"].get(content_url(ctx, completed["entry"]), HTTP_RANGE=f"bytes={size - 4}-")
    assert response.status_code == 206 and b"".join(response.streaming_content) == b"tail"
    async def read_prefix():
        source = stream_file_async(object_path(upload_key(record)), 0, size)
        assert len(await anext(source)) == 256 * 1024
        await source.aclose()
    tracemalloc.start()
    asyncio.run(read_prefix())
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 8 * 1024 ** 2


@pytest.mark.django_db(transaction=True)
def test_postgres_quota_serializes_concurrent_reservations(settings):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock concurrency requires a PostgreSQL test database")
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    settings.MY_DRIVE_QUOTA_BYTES = 10
    owner = get_user_model().objects.create_user(username="concurrent-drive")
    org = owner.owned_organizations.get()
    category = ApplicationCategory.objects.create(name="concurrent", slug="concurrent-drive")
    app = Application.objects.create(organization=org, category=category, created_by=owner, name="drive", slug="my-drive", kind="custom")
    space = DriveSpace.objects.create(organization=org, owner=owner)
    def reserve(_):
        close_old_connections()
        try:
            services.create_upload(space, app, {"name": "big", "size": 8, "last_modified": 0})
            return True
        except Exception as exc:
            from rest_framework.exceptions import ValidationError
            if not isinstance(exc, ValidationError):
                raise
            return False
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [False, True]

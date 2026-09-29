import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.agent_engine.models import TokenUsage
from modules.execution.models import Run, RunArtifact
from modules.execution.infrastructure.artifacts import get_artifact_storage
from app_center.animation_studio import runtime
from app_center.animation_studio.backend.serializers import AnimationInputSerializer
from app_center.animation_studio.backend.media import inspect_upload
from rest_framework.exceptions import ValidationError


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.ROOT_URLCONF = "app_center.animation_studio.backend.tests.urls"
    settings.ARTIFACT_ROOT = tmp_path / "artifacts"
    settings.ARTIFACT_STORAGE_BACKEND = "local"
    settings.AGENT_WORKSPACE_ROOT = tmp_path / "workspaces"
    owner = get_user_model().objects.create_user(username="anim-owner")
    other = get_user_model().objects.create_user(username="anim-other")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role=Membership.Role.ADMIN)
    call_command("sync_app_center", package_id="animation-studio", organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug="animation-studio")
    app.visibility = "organization"
    app.save(update_fields=["visibility"])
    client = APIClient()
    client.force_authenticate(owner)
    root = f"/api/v1/organizations/{org.id}"
    return SimpleNamespace(user=owner, other=other, org=org, app=app, client=client, root=root,
                           url=f"{root}/applications/{app.id}/animation-studio", tmp=tmp_path)


def generate(ctx, key="generate", **values):
    return ctx.client.post(ctx.url + "/generations", {"prompt": "解释番茄工作法", **values}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def save_artifact(ctx, run, kind="animation-source", content=b"zip"):
    key = f"test/{run.id}/{kind}"
    get_artifact_storage().put(key, content)
    return RunArtifact.objects.create(organization=ctx.org, run=run, kind=kind, object_key=key,
        content_hash=hashlib.sha256(content).hexdigest(), mime_type="application/zip", size=len(content))


def ready(ctx):
    result = generate(ctx)
    assert result.status_code == 201, result.data
    run = Run.objects.get(pk=result.data["id"])
    run.status = "succeeded"
    run.save(update_fields=["status"])
    save_artifact(ctx, run)
    return run


def export(ctx, run, key="export"):
    return ctx.client.post(f"{ctx.url}/generations/{run.id}/exports", {}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_sync_input_and_idempotency(ctx):
    call_command("sync_app_center", package_id="animation-studio", organization_id=str(ctx.org.id))
    assert ctx.app.revisions.count() == 1
    first = generate(ctx)
    assert first.status_code == 201, first.data
    assert first.data["input"]["action"] == "generate"
    assert first.data["input"]["duration"] == 30
    assert first.data["exports"] == []
    assert generate(ctx).data["id"] == first.data["id"]
    assert generate(ctx, prompt="different").status_code == 409
    assert generate(ctx, key="empty", prompt=" ").status_code == 400
    assert generate(ctx, key="long", duration=121).status_code == 400
    assert generate(ctx, key="ratio", aspect="wrong").status_code == 400
    assert ctx.client.post(ctx.url + "/generations", {"prompt": "hello"}, format="json").status_code == 400
    run = Run.objects.get(pk=first.data["id"])
    assert export(ctx, run).status_code == 400


def test_export_is_distinct_immutable_and_failure_keeps_generation(ctx):
    source = ready(ctx)
    output = export(ctx, source)
    assert output.status_code == 201, output.data
    assert output.data["id"] != str(source.id)
    assert output.data["input"] == {"action": "export", "source_run_id": str(source.id)}
    assert export(ctx, source).data["id"] == output.data["id"]
    revision = generate(ctx, key="revision", prompt="改成蓝色", source_run_id=str(source.id))
    assert revision.status_code == 201
    task = Run.objects.get(pk=output.data["id"])
    task.status = "failed"
    task.save(update_fields=["status"])
    source.refresh_from_db()
    assert source.status == "succeeded" and source.artifacts.count() == 1
    detail = ctx.client.get(f"{ctx.url}/generations/{source.id}").data
    assert detail["exports"][0]["status"] == "failed"
    assert ctx.client.get(f"{ctx.url}/generations/{revision.data['id']}").data["exports"] == []
    assert export(ctx, source, key="retry").status_code == 201
    assert ctx.client.get(ctx.url + "/generations").data["count"] == 2


def test_all_run_and_asset_surfaces_are_private(ctx):
    source = ready(ctx)
    task = Run.objects.get(pk=export(ctx, source).data["id"])
    artifact = save_artifact(ctx, task, "animation-video", b"video")
    assert ctx.client.get(f"{ctx.root}/runs/{task.id}/artifacts/{artifact.id}/access").status_code == 200
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(ctx.url + "/generations").data["count"] == 0
    assert export(ctx, source, "forbidden").status_code == 404
    assert generate(ctx, source_run_id=str(source.id)).status_code == 404
    for run in [source, task]:
        for suffix in ["", "/events", "/artifacts", "/attempts", "/stream", f"/artifacts/{artifact.id}/access"]:
            assert ctx.client.get(f"{ctx.root}/runs/{run.id}{suffix}").status_code == 404, suffix
        assert ctx.client.post(f"{ctx.root}/runs/{run.id}/commands", {"type": "cancel", "idempotency_key": "no"}, format="json").status_code == 404
    assert ctx.client.get(ctx.root + "/runs").data == []
    own_org = ctx.other.owned_organizations.get()
    assert ctx.client.get(ctx.url.replace(str(ctx.org.id), str(own_org.id)) + "/generations").status_code == 404


def test_artifact_access_exposes_signed_proxy_path_without_weakening_access(ctx):
    source = ready(ctx)
    artifact = save_artifact(ctx, source, "animation-preview", b"<!doctype html><p>Animation</p>")
    response = ctx.client.get(f"{ctx.root}/runs/{source.id}/artifacts/{artifact.id}/access", HTTP_HOST="127.0.0.1:8080")
    assert response.status_code == 200
    assert response.data["url"] == "http://127.0.0.1:8080" + response.data["content_path"]
    assert response.data["content_path"].startswith(f"{ctx.root}/runs/{source.id}/artifacts/{artifact.id}/content?token=")
    downloaded = ctx.client.get(response.data["content_path"])
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == b"<!doctype html><p>Animation</p>"
    unsigned = ctx.client.get(response.data["content_path"].split("?")[0])
    assert unsigned.status_code == 403


def test_upload_validates_real_content_and_owner(ctx):
    def upload(data):
        return ctx.client.post(ctx.url + "/assets", {"file": SimpleUploadedFile("image.png", data)}, format="multipart")
    assert upload(b"fake png").status_code == 400
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), "purple").save(buffer, format="PNG")
    response = upload(buffer.getvalue())
    assert response.status_code == 201, response.data
    assert response.data["mime_type"] == "image/png"
    assert "object_key" not in response.data
    assert generate(ctx, asset_ids=[response.data["id"]]).status_code == 201
    ctx.client.force_authenticate(ctx.other)
    assert generate(ctx, asset_ids=[response.data["id"]]).status_code == 400


class Sink:
    cancelled = False

    def __init__(self):
        self.events = []
        self.artifacts = []

    def emit(self, name, data):
        self.events.append((name, data))

    def create_artifact(self, **values):
        self.artifacts.append(values)


def response():
    return SimpleNamespace(success=True, content=json.dumps({"title": "示例", "storyboard": "流程讲解",
        "source": "import React from 'react'; export default function Animation(){return <div>示例</div>}"}),
        usage=TokenUsage(), model="test")


def payload(ctx, run):
    return {"organization_id": str(ctx.org.id), "run_id": str(run.id), "input": run.input, "effective_config": {}}


def test_generation_builds_preview_without_rendering_and_survives_workspace_cleanup(ctx):
    run = Run.objects.get(pk=generate(ctx).data["id"])
    sink = Sink()
    def build(arguments, workspace, sink, **kwargs):
        assert arguments[2] == "preview"
        output = Path(workspace) / "out"
        output.mkdir()
        (output / "preview.html").write_text("<!doctype html><h1>Preview</h1>", "utf-8")
    with patch.object(runtime.CodexAdapter, "complete", return_value=response()), patch.object(runtime, "run_process", side_effect=build):
        result = runtime.execute(payload(ctx, run), sink)
    assert result["preview_ready"]
    assert [a["kind"] for a in sink.artifacts] == ["animation-source", "animation-preview"]
    assert not list((ctx.tmp / "workspaces").rglob("Animation.tsx"))
    with zipfile.ZipFile(io.BytesIO(sink.artifacts[0]["content"])) as archive:
        assert "Animation.tsx" in archive.namelist()
        assert "package-lock.json" in archive.namelist()
        assert json.loads(archive.read("composition.json"))["durationInFrames"] == 900


def test_two_repairs_then_diagnostic_without_false_success(ctx):
    run = Run.objects.get(pk=generate(ctx).data["id"])
    sink = Sink()
    with patch.object(runtime.CodexAdapter, "complete", return_value=response()) as model, patch.object(runtime, "run_process", side_effect=RuntimeError("bad component")):
        with pytest.raises(RuntimeError, match="修复两次"):
            runtime.execute(payload(ctx, run), sink)
    assert model.call_count == 3
    assert [a["kind"] for a in sink.artifacts] == ["animation-diagnostic-source", "animation-diagnostic"]


def test_cancel_before_generation_never_calls_model(ctx):
    run = Run.objects.get(pk=generate(ctx).data["id"])
    sink = Sink()
    sink.cancelled = True
    with patch.object(runtime.CodexAdapter, "complete") as model:
        assert runtime.execute(payload(ctx, run), sink) == {"cancelled": True}
    model.assert_not_called()
    assert not sink.artifacts


def test_generic_run_input_cannot_skip_validation():
    serializer = AnimationInputSerializer(data={"action": "export", "prompt": "no version"})
    assert not serializer.is_valid()
    serializer = AnimationInputSerializer(data={"action": "generate", "prompt": "  "})
    assert not serializer.is_valid()


def test_archive_restore_does_not_restore_executable_configuration(ctx):
    source = ready(ctx)
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("Animation.tsx", "source")
        archive.writestr("composition.json", "{}")
        archive.writestr("assets.json", "[]")
        archive.writestr("../../escape", "bad")
        archive.writestr("runner.mjs", "bad")
        archive.writestr("assets/../escape", "bad")
    artifact = save_artifact(ctx, source, "test-source", content.getvalue())
    folder = ctx.tmp / "restored"
    folder.mkdir()
    runtime.read_archive(artifact, folder)
    assert set(item.name for item in folder.iterdir()) == {"Animation.tsx", "composition.json", "assets.json"}


@pytest.mark.parametrize("duration", [0, 121, float("nan")])
def test_recording_outside_supported_duration_is_rejected(duration):
    with patch("app_center.animation_studio.backend.media.probe", return_value={
        "format": {"format_name": "wav", "duration": duration}, "streams": [{"codec_type": "audio"}],
    }):
        with pytest.raises(ValidationError, match="5–120"):
            inspect_upload(SimpleUploadedFile("recording.wav", b"mock-audio"))


def test_recording_validates_container_and_keeps_non_integer_duration():
    info = {"format": {"format_name": "wav", "duration": "5.7"}, "streams": [{"codec_type": "audio"}]}
    with patch("app_center.animation_studio.backend.media.probe", return_value=info):
        _, data = inspect_upload(SimpleUploadedFile("recording.wav", b"mock-audio"))
        assert data == {"mime_type": "audio/wav", "duration": 5.7}
        with pytest.raises(ValidationError, match="纯音频"):
            inspect_upload(SimpleUploadedFile("spoof.mp3", b"mock-audio"))


def test_export_uses_archived_snapshot_without_model_or_new_generation(ctx):
    source = ready(ctx)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Animation.tsx", "original-source")
        archive.writestr("assets.json", "[]")
        archive.writestr("composition.json", json.dumps({"width": 1080, "height": 1920, "fps": 30, "durationInFrames": 171, "audioId": "recording"}))
    original = source.artifacts.get()
    get_artifact_storage().put(original.object_key, buffer.getvalue())
    task = Run.objects.get(pk=export(ctx, source).data["id"])
    sink = Sink()
    def render(arguments, workspace, sink, **kwargs):
        assert (Path(workspace) / "Animation.tsx").read_text() == "original-source"
        if arguments[0] != "ffmpeg":
            assert arguments[2] == "render"
            output = Path(workspace) / "out"
            output.mkdir()
            (output / "animation.mp4").write_bytes(b"video")
            (output / "cover.png").write_bytes(b"cover")
    info = {"format": {"duration": "5.7"}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}, {"codec_type": "audio"}]}
    with patch.object(runtime, "run_process", side_effect=render) as process, patch.object(runtime, "probe", return_value=info), patch.object(runtime.CodexAdapter, "complete") as model:
        result = runtime.execute(payload(ctx, task), sink)
    assert result["source_run_id"] == str(source.id)
    assert result["durationInFrames"] == 171
    assert process.call_count == 2
    model.assert_not_called()
    assert [a["kind"] for a in sink.artifacts] == ["animation-video", "animation-cover"]
    source.refresh_from_db()
    assert source.status == "succeeded"


def test_render_cancellation_kills_process_and_does_not_publish_artifacts(ctx):
    process = SimpleNamespace(poll=lambda: None)
    sink = Sink()
    checks = 0
    def cancellation(_sink):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise runtime.Cancelled()
    with patch.object(runtime.subprocess, "Popen", return_value=process), patch.object(runtime, "stop_process") as stop, patch.object(runtime, "check_cancel", side_effect=cancellation):
        with pytest.raises(runtime.Cancelled):
            runtime.run_process(["node", "runner"], ctx.tmp, sink)
    stop.assert_called_once_with(process)
    assert not sink.artifacts

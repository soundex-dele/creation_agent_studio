import hashlib
import io
import json
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
from core.agent_engine.adapters.codex import _codex_tool_payload
from core.agent_engine.adapters.codex import _AppServerTurn
from modules.execution.models import Run, RunArtifact
from modules.execution.infrastructure.artifacts import get_artifact_storage
from app_center.ai_drawing.runtime import execute, _read_output
from ..models import DrawingReference


def png():
    stream = io.BytesIO()
    Image.new("RGB", (24, 16), "purple").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.ROOT_URLCONF = "app_center.ai_drawing.backend.tests.urls"
    settings.ARTIFACT_ROOT = tmp_path / "artifacts"
    settings.ARTIFACT_STORAGE_BACKEND = "local"
    settings.AGENT_WORKSPACE_ROOT = tmp_path / "workspaces"
    settings.CODEX_TRANSPORT = "app-server"
    user = get_user_model().objects.create_user(username="drawing-owner")
    other = get_user_model().objects.create_user(username="drawing-other")
    org = user.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role=Membership.Role.ADMIN)
    call_command("sync_app_center", package_id="ai-drawing", organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug="ai-drawing")
    app.visibility = "organization"
    app.save(update_fields=["visibility"])
    client = APIClient()
    client.force_authenticate(user)
    root = f"/api/v1/organizations/{org.id}"
    return SimpleNamespace(user=user, other=other, org=org, app=app, client=client, root=root,
                           url=f"{root}/applications/{app.id}/ai-drawing", tmp=tmp_path)


def generate(ctx, key="test-drawing", **values):
    return ctx.client.post(ctx.url + "/generations", {"prompt": "一只紫色小猫", **values}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def upload(ctx, content=None):
    return ctx.client.post(ctx.url + "/references", {"file": SimpleUploadedFile("ref.png", png() if content is None else content, content_type="image/png")}, format="multipart")


def artifact(ctx, run):
    content = png()
    get_artifact_storage().put(f"test/{run.id}.png", content)
    return RunArtifact.objects.create(organization=ctx.org, run=run, kind="drawing", object_key=f"test/{run.id}.png",
        content_hash=hashlib.sha256(content).hexdigest(), mime_type="image/png", size=len(content), metadata={"width": 24, "height": 16})


def test_manifest_sync_and_idempotency(ctx):
    call_command("sync_app_center", package_id="ai-drawing", organization_id=str(ctx.org.id))
    assert ctx.app.revisions.count() == 1
    first = generate(ctx)
    assert first.status_code == 201, first.data
    second = generate(ctx)
    assert second.status_code == 200 and second.data["id"] == first.data["id"]
    assert first.data["max_attempts"] == 1 and not first.data["retry_safe"]
    assert first.data["executor_key"] == "ai-drawing"
    assert generate(ctx, prompt="另一个提示词").status_code == 409
    assert generate(ctx, key="empty", prompt="  ").status_code == 400
    assert generate(ctx, key="bad", orientation="wrong").status_code == 400
    assert ctx.client.post(ctx.url + "/generations", {"prompt": "猫"}, format="json").status_code == 400
    assert ctx.client.get(ctx.url + "/generations").data["count"] == 1


def test_reference_validation_and_access(ctx):
    assert upload(ctx, b"not a real png").status_code == 400
    assert upload(ctx, b"x" * (20 * 1024 * 1024 + 1)).status_code == 400
    result = upload(ctx)
    assert result.status_code == 201, result.data
    assert result.data["width"] == 24 and "object_key" not in result.data
    reference_id = result.data["id"]
    content = ctx.client.get(ctx.url + f"/references/{reference_id}/content")
    assert content.status_code == 200
    assert b"".join(content.streaming_content) == png()
    assert generate(ctx, reference_id=reference_id).status_code == 201
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(ctx.url + f"/references/{reference_id}/content").status_code == 404
    assert generate(ctx, reference_id=reference_id).status_code == 404


def test_history_edit_and_all_generic_run_surfaces_are_private(ctx):
    result = generate(ctx)
    run = Run.objects.get(pk=result.data["id"])
    output = artifact(ctx, run)
    first = ctx.client.get(ctx.url + f"/generations/{run.id}")
    assert first.data["artifacts"][0]["id"] == str(output.id)
    assert generate(ctx, key="edit", source_artifact_id=str(output.id)).status_code == 201
    reference_id = upload(ctx).data["id"]
    assert generate(ctx, key="both", source_artifact_id=str(output.id), reference_id=reference_id).status_code == 400
    access = ctx.client.get(f"{ctx.root}/runs/{run.id}/artifacts/{output.id}/access")
    assert access.status_code == 200
    downloaded = ctx.client.get(access.data["url"])
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == png()
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(ctx.url + "/generations").data["count"] == 0
    assert ctx.client.get(ctx.url + f"/generations/{run.id}").status_code == 404
    assert generate(ctx, key="steal", source_artifact_id=str(output.id)).status_code == 404
    for suffix in ["", "/events", "/artifacts", "/attempts", "/stream", f"/artifacts/{output.id}/access"]:
        assert ctx.client.get(f"{ctx.root}/runs/{run.id}{suffix}").status_code == 404, suffix
    assert ctx.client.get(ctx.root + "/runs").data == []
    assert ctx.client.delete(f"{ctx.root}/runs/{run.id}").status_code == 404
    assert ctx.client.post(f"{ctx.root}/runs/{run.id}/commands", {"type": "cancel", "idempotency_key": "forbidden"}, format="json").status_code == 404
    own_org = ctx.other.owned_organizations.get()
    assert ctx.client.get(ctx.url.replace(str(ctx.org.id), str(own_org.id)) + "/generations").status_code == 404
    ctx.client.force_authenticate(ctx.user)
    ctx.app.is_active = False
    ctx.app.save(update_fields=["is_active"])
    assert ctx.client.get(f"{ctx.root}/runs/{run.id}").status_code == 404


class Sink:
    cancelled = False

    def __init__(self):
        self.events = []
        self.artifacts = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))

    def create_artifact(self, **artifact):
        self.artifacts.append(artifact)


def execute_run(ctx, sink, **input):
    response = generate(ctx, **input)
    assert response.status_code == 201, response.data
    run = Run.objects.get(pk=response.data["id"])
    return execute({"run_id": str(run.id), "organization_id": str(ctx.org.id), "input": run.input, "effective_config": {}}, sink)


def complete_image(messages, **options):
    path = Path(options["working_directory"]) / "image.png"
    path.write_bytes(png())
    options["on_event"]("tool.started", {"tool_type": "imageGeneration"})
    options["on_event"]("tool.completed", {"tool_type": "imageGeneration", "tool_call_id": "image-1", "status": "completed", "saved_path": str(path), "revised_prompt": "revised"})
    # Must not leak unrelated tools or agent text into Run events.
    options["on_event"]("output.delta", {"text": str(path)})
    return SimpleNamespace(success=True)


def test_runtime_archives_real_image_and_sanitizes_events(ctx):
    sink = Sink()
    with patch("app_center.ai_drawing.runtime.CodexAdapter.complete", side_effect=complete_image) as complete:
        output = execute_run(ctx, sink)
    assert output["images"][0]["width"] == 24
    assert sink.artifacts[0]["content"] == png()
    assert sink.artifacts[0]["metadata"]["revised_prompt"] == "revised"
    assert str(ctx.tmp) not in json.dumps(sink.events)
    options = complete.call_args.kwargs
    assert not Path(options["working_directory"]).exists()
    assert not options.get("thread_id") and options["thread_config"]["features.image_generation"]


def test_runtime_reference_and_history_edit_are_local_images(ctx):
    reference_id = upload(ctx).data["id"]
    def complete(messages, **options):
        assert len(options["image_paths"]) == 1
        assert Path(options["image_paths"][0]).read_bytes() == png()
        return complete_image(messages, **options)
    with patch("app_center.ai_drawing.runtime.CodexAdapter.complete", side_effect=complete):
        execute_run(ctx, Sink(), reference_id=reference_id)
        source = artifact(ctx, Run.objects.get(input__reference_id=reference_id))
        execute_run(ctx, Sink(), key="edit", source_artifact_id=str(source.id))


@pytest.mark.parametrize("outcome, expected", [(SimpleNamespace(success=True), "未返回可用图片"), (SimpleNamespace(success=False), "未完成生图"), (TimeoutError("生图超时"), "超时"), (RuntimeError("secret/path"), "登录状态")])
def test_runtime_failure_and_timeout(ctx, outcome, expected):
    with patch("app_center.ai_drawing.runtime.CodexAdapter.complete", side_effect=outcome if isinstance(outcome, Exception) else lambda *a, **kw: outcome):
        with pytest.raises(Exception, match=expected):
            execute_run(ctx, Sink())


def test_cancel_preserves_already_generated_image(ctx):
    sink = Sink()
    def cancel_after_image(messages, **options):
        result = complete_image(messages, **options)
        sink.cancelled = True
        return result
    with patch("app_center.ai_drawing.runtime.CodexAdapter.complete", side_effect=cancel_after_image):
        assert execute_run(ctx, sink)["images"]
    assert len(sink.artifacts) == 1


def test_cancel_before_execution_does_not_call_codex(ctx):
    sink = Sink()
    sink.cancelled = True
    with patch("app_center.ai_drawing.runtime.CodexAdapter.complete") as complete:
        assert execute_run(ctx, sink) == {}
    complete.assert_not_called()


@pytest.mark.parametrize("outcome", ["succeeded", "cancelled", "no_image"])
def test_locked_workspace_does_not_change_drawing_outcome(ctx, outcome):
    sink = Sink()

    def complete(messages, **options):
        result = (SimpleNamespace(success=True) if outcome == "no_image"
                  else complete_image(messages, **options))
        sink.cancelled = outcome == "cancelled"
        return result

    with (
        patch("app_center.ai_drawing.runtime.CodexAdapter.complete", side_effect=complete),
        patch("app_center.ai_drawing.runtime.shutil.rmtree", side_effect=PermissionError("WinError 32")),
        patch("app_center.ai_drawing.runtime.time.sleep"),
    ):
        if outcome == "no_image":
            with pytest.raises(RuntimeError, match="未返回可用图片"):
                execute_run(ctx, sink)
        else:
            assert execute_run(ctx, sink)["images"]
            assert sink.artifacts[0]["content"] == png()


def test_output_path_validation(tmp_path):
    path = tmp_path / "outside.png"
    path.write_bytes(png())
    with pytest.raises(RuntimeError, match="目录"):
        _read_output(str(path), tmp_path / "workspace")
    with pytest.raises(RuntimeError, match="保存路径"):
        _read_output(None, tmp_path)
    with pytest.raises(RuntimeError, match="丢失"):
        _read_output(str(tmp_path / "missing.png"), tmp_path)


def test_codex_image_event_does_not_forward_base64():
    payload = _codex_tool_payload({"type": "imageGeneration", "id": "image", "status": "completed", "result": "large base64", "savedPath": "C:/generated/image.png", "revisedPrompt": "a cat"})
    assert "result" not in payload
    assert payload["saved_path"] == "C:/generated/image.png"
    assert payload["revised_prompt"] == "a cat"


def test_codex_turn_enforces_deadline():
    from unittest.mock import Mock
    import queue
    import time
    transport = Mock()
    transport.request.return_value = {"turn": {"id": "turn"}}
    transport.next_notification.side_effect = queue.Empty
    turn = _AppServerTurn(transport=transport, thread_id="thread", text="draw", model="")
    turn.deadline = time.monotonic() + 1
    with pytest.raises(TimeoutError, match="超时"):
        list(turn.stream())
    assert transport.next_notification.call_args.kwargs["timeout"] <= 1


@pytest.mark.django_db(transaction=True)
def test_coordinator_persists_drawing_before_success(ctx):
    import queue
    import threading
    from modules.execution.infrastructure.claim import claim_next_run
    from modules.execution.infrastructure.coordinator import ExecutionCoordinator
    from modules.execution.runtime.child import ChildEventSink

    response = generate(ctx)
    run = Run.objects.get(pk=response.data["id"])
    claimed = claim_next_run(worker_id="drawing-test", worker_pool="media", lease_seconds=30, executor_keys=("ai-drawing",))
    coordinator = ExecutionCoordinator(worker_id="drawing-test", worker_pool="media", adapter_entries={"ai-drawing": "app_center.ai_drawing.runtime.execute"})
    messages = queue.Queue()
    sink = ChildEventSink(messages, threading.Event())
    with patch("app_center.ai_drawing.runtime.CodexAdapter.complete", side_effect=complete_image):
        output = execute(coordinator._payload(claimed), sink)
    active = SimpleNamespace(claimed=claimed)
    while not messages.empty():
        assert coordinator._handle_message(active, messages.get()) is False
    run.refresh_from_db()
    assert run.status == Run.Status.RUNNING
    image = run.artifacts.get(kind="drawing")
    with get_artifact_storage().open(image.object_key) as handle:
        assert handle.read() == png()
    coordinator._finish(active, {"outcome": "succeeded", "output": output})
    run.refresh_from_db()
    assert run.status == Run.Status.SUCCEEDED
    events = list(run.events.order_by("sequence").values_list("type", flat=True))
    assert "progress.updated" in events
    assert events.index("artifact.created") < events.index("run.succeeded")

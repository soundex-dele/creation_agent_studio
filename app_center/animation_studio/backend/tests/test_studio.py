import copy
import io
import json
from unittest.mock import Mock, patch
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError
from .test_animation import ctx, generate, ready, save_artifact
from ..documents import empty_document, scene, validate_document, builtins
from ..models import AnimationProject, AnimationVersion, AnimationBatch, AnimationSpeechConfig
from ..projects import import_history
from ..batch import execute_batch
from ...studio_runtime import subtitle_text
from ...speech import synthesize


def document():
    result = empty_document(); result["prompt"] = "测试动画"; result["scenes"] = [scene("第一幕", "测试内容", 300), scene("第二幕", "更多内容", 300)]
    return result


def create(ctx, doc=None):
    result = ctx.client.post(ctx.url + "/projects", {"title": "新作品", "draft": doc or document()}, format="json")
    assert result.status_code == 201, result.data
    return result.data


def test_project_draft_conflict_and_owner_isolation(ctx):
    p = create(ctx); doc = document()
    url = f"{ctx.url}/projects/{p['id']}/draft"
    saved = ctx.client.put(url, {"revision": 1, "document": doc}, format="json")
    assert saved.status_code == 200 and saved.data["revision"] == 2
    assert ctx.client.put(url, {"revision": 1, "document": document()}, format="json").status_code == 409
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(f"{ctx.url}/projects/{p['id']}").status_code == 404
    assert ctx.client.put(url, {"revision": 2, "document": doc}, format="json").status_code == 404


def test_lock_requires_separate_unlock_and_keeps_scene_unchanged(ctx):
    doc = document(); doc["scenes"][0]["locked"] = True; p = create(ctx, doc)
    changed = copy.deepcopy(doc); changed["scenes"][0]["body"] = "changed"
    url = f"{ctx.url}/projects/{p['id']}/draft"
    assert ctx.client.put(url, {"revision": 1, "document": changed}, format="json").status_code == 400
    changed["scenes"][0]["locked"] = False
    assert ctx.client.put(url, {"revision": 1, "document": changed}, format="json").status_code == 400
    doc["scenes"][0]["locked"] = False
    assert ctx.client.put(url, {"revision": 1, "document": doc}, format="json").status_code == 200


def test_scene_tasks_snapshot_and_idempotency(ctx):
    p = create(ctx)
    body = {"action": "generate", "revision": 1}
    url = f"{ctx.url}/projects/{p['id']}/tasks"
    first = ctx.client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="studio-generate")
    second = ctx.client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="studio-generate")
    assert first.status_code == 201, first.data
    assert second.status_code == 200 and first.data["id"] == second.data["id"]
    version = AnimationVersion.objects.get(run_id=first.data["id"])
    assert version.document == p["draft"]
    new = copy.deepcopy(p["draft"]); new["scenes"][0]["body"] = "later"
    ctx.client.put(f"{ctx.url}/projects/{p['id']}/draft", {"revision": 1, "document": new}, format="json")
    version.refresh_from_db()
    assert version.document != new
    # The accepted snapshot remains replayable even after the draft advanced.
    replay = ctx.client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="studio-generate")
    assert replay.status_code == 200 and replay.data["id"] == first.data["id"]


def test_history_import_groups_only_own_chain_and_is_repeatable(ctx):
    parent = ready(ctx)
    child = generate(ctx, key="child", source_run_id=str(parent.id))
    from modules.execution.models import Run
    foreign = Run.objects.get(pk=child.data["id"]); foreign.owner = ctx.other; foreign.save(update_fields=["owner"])
    import_history(ctx.user, ctx.app); import_history(ctx.user, ctx.app)
    assert AnimationProject.objects.filter(owner=ctx.user).count() == 1
    assert AnimationVersion.objects.filter(project__owner=ctx.user).count() == 1
    import_history(ctx.other, ctx.app)
    assert AnimationProject.objects.filter(owner=ctx.other).count() == 1
    assert AnimationVersion.objects.get(run=parent).project_id != AnimationVersion.objects.get(run=foreign).project_id


def test_restore_and_conversion_preserve_legacy(ctx):
    run = ready(ctx); import_history(ctx.user, ctx.app)
    version = AnimationVersion.objects.get(run=run); p = version.project
    result = ctx.client.post(f"{ctx.url}/projects/{p.id}/convert", {"version_id": str(version.id)}, format="json")
    assert result.status_code == 201 and result.data["id"] != str(p.id)
    p.refresh_from_db(); assert p.draft["schema_version"] == 1
    assert result.data["draft"]["schema_version"] == 2
    restore = ctx.client.post(f"{ctx.url}/projects/{p.id}/restore", {"version_id": str(version.id), "revision": 1}, format="json")
    assert restore.status_code == 200 and restore.data["revision"] == 2


@pytest.mark.parametrize("mutate", [lambda d: d["scenes"][0].update(frames=float("nan")), lambda d: d.update(aspect="4:3"), lambda d: d["scenes"][0]["style"].update(color="url(x)"), lambda d: d.update(audio=[{"role": "music", "asset_id": "invalid"}])])
def test_invalid_documents_rejected(mutate):
    doc = document(); mutate(doc)
    with pytest.raises(ValidationError): validate_document(doc, complete=True)


def test_export_specs_and_subtitle_timestamps(ctx):
    run = ready(ctx)
    result = ctx.client.post(f"{ctx.url}/generations/{run.id}/exports", {"format": "gif", "resolution": 720}, format="json", HTTP_IDEMPOTENCY_KEY="gif")
    assert result.status_code == 201 and result.data["input"]["export_options"]["resolution"] == 720
    assert ctx.client.post(f"{ctx.url}/generations/{run.id}/exports", {"format": "avi"}, format="json", HTTP_IDEMPOTENCY_KEY="bad").status_code == 400
    doc = {"subtitles": [{"start": 15, "end": 61, "text": "测试"}]}
    assert "00:00:00,500 --> 00:00:02,033" in subtitle_text(doc, "srt")
    assert subtitle_text(doc, "vtt").startswith("WEBVTT\n\n")


def test_csv_xlsx_import_rejects_formula_and_maps_columns(ctx):
    result = ctx.client.post(ctx.url + "/batches/import", {"file": SimpleUploadedFile("batch.csv", "标题,正文\n你好,内容\n".encode())})
    assert result.status_code == 200 and result.data["sheets"][0]["rows"][0]["正文"] == "内容"
    from openpyxl import Workbook
    book = Workbook(); book.active.append(["title"]); book.active.append(["=1+1"])
    stream = io.BytesIO(); book.save(stream)
    assert ctx.client.post(ctx.url + "/batches/import", {"file": SimpleUploadedFile("batch.xlsx", stream.getvalue())}).status_code == 400


def test_batch_validation_is_atomic_and_submission_idempotent(ctx):
    body = {"template_id": "knowledge", "rows": [{"text1": "a", "text2": "b", "text3": "c"}]}
    validated = ctx.client.post(ctx.url + "/batches", {**body, "validate_only": True}, format="json")
    assert validated.status_code == 200 and AnimationBatch.objects.count() == 0
    bad = ctx.client.post(ctx.url + "/batches", {**body, "rows": [{"text1": "a"}]}, format="json", HTTP_IDEMPOTENCY_KEY="batch")
    assert bad.status_code == 400 and AnimationBatch.objects.count() == 0
    first = ctx.client.post(ctx.url + "/batches", body, format="json", HTTP_IDEMPOTENCY_KEY="batch")
    second = ctx.client.post(ctx.url + "/batches", body, format="json", HTTP_IDEMPOTENCY_KEY="batch")
    assert first.status_code == 201, first.data
    assert second.data["id"] == first.data["id"] and AnimationBatch.objects.count() == 1


def test_batch_dispatches_only_two_children_and_resume_reuses_them(ctx):
    body = {"template_id": "knowledge", "rows": [{"text1": "a", "text2": "b", "text3": "c"}] * 4}
    response = ctx.client.post(ctx.url + "/batches", body, format="json", HTTP_IDEMPOTENCY_KEY="batch-workers")
    batch = AnimationBatch.objects.get(pk=response.data["id"])
    sink = Mock(cancelled=False)
    execute_batch({}, sink, batch.run, ctx.app, {"batch_id": str(batch.id)})
    assert batch.run.child_runs.count() == 2
    assert len(sink.wait_for_children.call_args.kwargs["child_run_ids"]) == 2
    execute_batch({}, sink, batch.run, ctx.app, {"batch_id": str(batch.id)})
    assert batch.run.child_runs.count() == 2


def test_speech_settings_permission_and_stream_contract(ctx, monkeypatch):
    from apps.enterprise.models import SecretReference, Membership
    SecretReference.objects.create(organization=ctx.org, name="tts", reference="TEST_ANIMATION_TTS")
    monkeypatch.setenv("TEST_ANIMATION_TTS", "private-test-key")
    data = {"enabled": True, "app_id": "app", "resource_id": "seed-tts-2.0", "secret_ref": "tts", "voices": [{"id": "speaker", "name": "测试音色"}]}
    result = ctx.client.put(ctx.url + "/speech-config", data, format="json")
    assert result.status_code == 200, result.data
    assert "private-test-key" not in json.dumps(result.data)
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    response.iter_lines.return_value = [b'{"code":0,"data":"YXVkaW8="}', b'{"code":20000000}']
    with patch("app_center.animation_studio.speech.requests.post", return_value=response) as post:
        assert synthesize(ctx.app, "测试", "speaker", 1.2) == b"audio"
        assert post.call_args.kwargs["json"]["req_params"]["audio_params"]["speech_rate"] == 20
    response.iter_lines.return_value = [b'{"code":0,"data":"YXVkaW8="}']
    with patch("app_center.animation_studio.speech.requests.post", return_value=response), pytest.raises(RuntimeError, match="未完成"):
        synthesize(ctx.app, "测试", "speaker", 1)
    Membership.objects.filter(user=ctx.other, organization=ctx.org).update(role="viewer")
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.put(ctx.url + "/speech-config", data, format="json").status_code == 403


@pytest.mark.parametrize("action", ["generate", "scene"])
def test_worker_preserves_other_scene_and_does_not_overwrite_newer_draft(ctx, monkeypatch, action):
    from modules.execution.models import Run
    from ... import studio_runtime, runtime
    doc = document()
    for item in doc["scenes"]: item["source"] = "export default function Scene({scene}) {return scene.title}"
    doc["scenes"][0]["locked"] = True
    p = create(ctx, doc)
    request = {"action": action, "revision": 1, "scene_id": doc["scenes"][1]["id"], "instruction": "只修改第二幕"}
    response = ctx.client.post(f"{ctx.url}/projects/{p['id']}/tasks", request, format="json", HTTP_IDEMPOTENCY_KEY="worker-test")
    assert response.status_code == 201, response.data
    run = Run.objects.get(pk=response.data["id"]); run.status = "running"; run.save(update_fields=["status"])
    changed = copy.deepcopy(doc); changed["prompt"] = "用户后来更新的草稿"
    AnimationProject.objects.filter(pk=p["id"]).update(draft=changed, revision=2)
    ai = Mock(return_value={"source": "export default function Scene({scene}) {return scene.body}"})
    monkeypatch.setattr(studio_runtime, "ask", ai)
    def build(arguments, workspace, sink, **kwargs):
        (workspace / "out").mkdir(exist_ok=True)
        (workspace / "Animation.tsx").write_text("export default ()=>null", encoding="utf-8")
        (workspace / "out/preview.html").write_text("<!doctype html><p>preview</p>", encoding="utf-8")
        (workspace / "out/cover.png").write_bytes(b"png")
    monkeypatch.setattr(studio_runtime, "run_process", build)
    sink = Mock(cancelled=False)
    result = runtime.execute({"run_id": str(run.id), "organization_id": str(ctx.org.id)}, sink)
    assert result["draft_applied"] is False
    assert AnimationProject.objects.get(pk=p["id"]).draft == changed
    artifact = next(c.kwargs for c in sink.create_artifact.call_args_list if c.kwargs["kind"] == "animation-document")
    produced = json.loads(artifact["content"])
    assert produced["scenes"][0] == doc["scenes"][0]
    if action == "scene":
        assert ai.call_count == 1
        assert produced["scenes"][1]["source"] != doc["scenes"][1]["source"]
    else:
        assert not ai.called
        assert AnimationVersion.objects.get(run=run).document == doc

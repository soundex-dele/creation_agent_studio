import copy
import io
import json
import wave
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from modules.catalog.models import ApplicationRevision, ApplicationDeployment
from modules.catalog.services import canonical_content_hash
from modules.execution.models import Run, RunAttempt, RunLease
from app_center.documents.backend.models import Document
from app_center.ideas_todos.backend.models import Todo
from ..models import Recording, ActionItem
from ..storage import object_path, probe_audio, MAX_BYTES
from ..analysis import SECTIONS, validate_analysis, chunks, analyze
from ..serializers import action_revision
from ...runtime import execute_meeting


def wav_file(name="meeting.wav"):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    return SimpleUploadedFile(name, output.getvalue(), content_type="audio/wav")


def segments():
    return [{"id": "s1", "start": 0.0, "end": 5.0, "text": "决定周五发布。小王准备材料。", "original_text": "决定周五发布。小王准备材料。"},
            {"id": "s2", "start": 5.0, "end": 10.0, "text": "用户反馈非常重要。", "original_text": "用户反馈非常重要。"}]


def analysis_data():
    return {**{key: [] for key in SECTIONS}, "topics": [{"text": "讨论发布时间", "segment_ids": ["s1"]}],
        "decisions": [{"text": "周五发布", "segment_ids": ["s1"]}],
        "actions": [{"title": "准备材料", "description": "原文负责人：小王", "priority": 2, "due_date": None, "segment_ids": ["s1"]}]}


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.MEETING_AUDIO_ROOT = tmp_path / "private"
    owner = get_user_model().objects.create_user(username="meeting-owner")
    reader = get_user_model().objects.create_user(username="meeting-reader")
    outsider = get_user_model().objects.create_user(username="meeting-outsider")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=reader, role=Membership.Role.ADMIN)
    category, _ = ApplicationCategory.objects.get_or_create(slug="meeting-test", defaults={"name": "会议测试"})
    apps = {}
    for slug in ("meeting-assistant", "documents", "ideas-todos"):
        apps[slug] = Application.objects.create(organization=org, category=category, name=slug, slug=slug,
            created_by=owner, kind="custom", visibility="organization")
    app = apps["meeting-assistant"]
    content = yaml.safe_load((Path(__file__).parents[2] / "application.yaml").read_text(encoding="utf-8"))["spec"]["definition"]
    revision = ApplicationRevision.objects.create(organization=org, application=app, revision_no=1,
        content=content, content_hash=canonical_content_hash(content), created_by=owner)
    ApplicationDeployment.objects.create(organization=org, application=app, revision=revision, updated_by=owner)
    client = APIClient()
    client.force_authenticate(owner)
    root = f"/api/v1/organizations/{org.id}/applications/{app.id}/meeting-assistant"
    response = client.post(root + "/records", {"audio": wav_file(), "title": "产品访谈", "kind": "interview", "recorded_on": "2026-09-24"}, format="multipart")
    assert response.status_code == 201, response.data
    record = Recording.objects.get(pk=response.data["id"])
    return {"client": client, "owner": owner, "reader": reader, "outsider": outsider, "org": org,
        "apps": apps, "app": app, "record": record, "root": root, "url": f"{root}/records/{record.pk}"}


def ready(ctx):
    record = ctx["record"]
    Run.objects.filter(pk=record.active_run_id).update(status="succeeded")
    record.refresh_from_db()
    record.segments = segments()
    record.stage = "completed"
    record.analysis_version = record.version
    data = analysis_data()
    actions = data.pop("actions")
    record.analysis = data
    record.save()
    for item in actions:
        ActionItem.objects.create(organization=ctx["org"], recording=record, analysis_version=record.version, **item)
    return record


def post(ctx, suffix, data=None, key="request-1"):
    if suffix == "/confirm-actions" and "action_versions" not in (data or {}):
        data = {**(data or {}), "action_versions": {str(item.pk): action_revision(item) for item in ctx["record"].actions.all()}}
    return ctx["client"].post(ctx["url"] + suffix, data or {}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def claim(ctx):
    record = ctx["record"]
    run = Run.objects.get(pk=record.active_run_id)
    attempt = RunAttempt.objects.create(run=run, attempt_no=1, worker_pool="media", status="running")
    RunLease.objects.create(attempt=attempt, worker_id="test", epoch=1, heartbeat_at=timezone.now(), expires_at=timezone.now() + timedelta(minutes=5))
    run.status = "running"
    run.current_attempt = attempt
    run.save()
    return {"run_id": str(run.pk), "attempt_id": str(attempt.pk), "organization_id": str(run.organization_id), "input": run.input}, SimpleNamespace(cancelled=False, emit=Mock())


def test_upload_queues_privately_and_list(ctx):
    record = ctx["record"]
    assert record.active_run.status == "queued"
    assert record.size > 0 and record.duration == pytest.approx(.1)
    assert object_path(record.object_key).exists()
    listed = ctx["client"].get(ctx["root"] + "/records", {"search": "访谈"}).data
    assert listed["count"] == 1 and "segments" not in listed["results"][0]
    assert "object_key" not in ctx["client"].get(ctx["url"]).data
    assert Todo.objects.count() == 0 and Document.objects.count() == 0


def test_owner_tenant_and_application_isolation(ctx):
    client = ctx["client"]
    client.force_authenticate(ctx["reader"])
    assert client.get(ctx["url"]).status_code == 404
    assert client.get(ctx["root"] + "/records").data["count"] == 0
    assert post(ctx, "/access").status_code == 404
    run = ctx["record"].active_run
    assert client.get(f"/api/v1/organizations/{ctx['org'].id}/runs/{run.pk}").status_code == 404
    client.force_authenticate(ctx["outsider"])
    assert client.get(ctx["url"]).status_code in (403, 404)
    client.force_authenticate(ctx["owner"])
    bad = ctx["url"].replace(str(ctx["org"].id), str(ctx["outsider"].owned_organizations.get().id))
    assert client.get(bad).status_code in (403, 404)
    ctx["app"].is_active = False
    ctx["app"].save()
    assert client.get(ctx["url"]).status_code == 404


def test_invalid_uploads_and_limits(ctx, monkeypatch):
    endpoint = ctx["root"] + "/records"
    fields = {"title": "bad", "kind": "meeting", "recorded_on": "2026-09-24"}
    for file in [SimpleUploadedFile("a.exe", b"bad"), SimpleUploadedFile("a.mp3", b"not audio"), SimpleUploadedFile("a.wav", b"")]:
        response = ctx["client"].post(endpoint, {**fields, "audio": file}, format="multipart")
        assert response.status_code == 400
    assert Recording.objects.count() == 1
    from ..storage import store_upload
    large = SimpleNamespace(name="x.wav", size=MAX_BYTES + 1)
    with pytest.raises(Exception, match="200 MiB"):
        store_upload(large, "large.wav")
    with pytest.raises(ValueError):
        object_path("../outside.wav")
    import av
    fake = Mock()
    fake.__enter__ = Mock(return_value=fake)
    fake.__exit__ = Mock(return_value=False)
    fake.streams.audio = [SimpleNamespace(duration=7201, time_base=1)]
    monkeypatch.setattr(av, "open", lambda *a: fake)
    with pytest.raises(Exception, match="两小时"):
        probe_audio("fake")


def test_playback_range_head_tamper_and_revocation(ctx):
    token = post(ctx, "/access").data["token"]
    url = ctx["root"] + "/content?token=" + token
    public = APIClient()
    response = public.get(url, HTTP_RANGE="bytes=0-9")
    assert response.status_code == 206 and b"".join(response.streaming_content)[:4] == b"RIFF"
    assert public.head(url).status_code == 200
    assert public.get(url, HTTP_RANGE="bytes=999999-").status_code == 416
    assert public.get(url + "bad").status_code == 403
    ctx["app"].is_active = False
    ctx["app"].save()
    assert public.get(url).status_code == 404


def test_correction_preserves_original_and_blocks_stale_actions(ctx):
    record = ready(ctx)
    original = copy.deepcopy(record.segments)
    response = ctx["client"].patch(ctx["url"] + "/transcript", {"version": 1, "segments": [{"id": "s1", "text": "改为周六发布"}]}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["version"] == 2 and response.data["stale"]
    segment = response.data["segments"][0]
    assert segment["original_text"] == original[0]["original_text"] and segment["start"] == original[0]["start"]
    assert ctx["client"].patch(ctx["url"] + "/transcript", {"version": 1, "segments": [{"id": "s1", "text": "old"}]}, format="json").status_code == 409
    assert post(ctx, "/confirm-actions", {"version": 2, "confirmed": True, "action_ids": [str(record.actions.first().pk)]}).status_code == 409
    assert post(ctx, "/documents", {"kind": "minutes", "version": 2}).status_code == 409
    assert post(ctx, "/documents", {"kind": "transcript", "version": 2}).status_code == 201


def test_only_explicit_confirmation_creates_todos_and_repeats_are_safe(ctx):
    record = ready(ctx)
    action = record.actions.first()
    body = {"version": 1, "action_ids": [str(action.pk)]}
    assert post(ctx, "/confirm-actions", body).status_code == 400
    assert Todo.objects.count() == 0
    changed = ctx["client"].patch(ctx["url"] + f"/actions/{action.pk}", {"version": 1, "revision": action_revision(action), "title": "准备发布材料", "due_date": "2026-09-25", "priority": 3}, format="json")
    assert changed.status_code == 200 and Todo.objects.count() == 0
    for _ in range(2):
        result = post(ctx, "/confirm-actions", {**body, "confirmed": True})
        assert result.status_code == 200, result.data
    todo = Todo.objects.get()
    assert todo.title == "准备发布材料" and todo.owner_id == ctx["owner"].id
    assert "00:00:00" in todo.description and todo.priority == 3
    todo.delete()
    assert post(ctx, "/confirm-actions", {**body, "confirmed": True}).status_code == 200
    assert Todo.objects.count() == 0


def test_exports_are_grounded_idempotent_and_independent(ctx, django_capture_on_commit_callbacks):
    record = ready(ctx)
    body = {"kind": "materials", "version": 1}
    first = post(ctx, "/documents", body)
    assert first.status_code == 201, first.data
    assert post(ctx, "/documents", body).data == first.data
    assert post(ctx, "/documents", {"kind": "minutes", "version": 1}).status_code == 409
    doc = Document.objects.get()
    assert "00:00:00" in doc.plain_text and "主题摘要" in doc.plain_text and "文章提纲" in doc.plain_text
    post(ctx, "/confirm-actions", {"version": 1, "confirmed": True, "action_ids": [str(record.actions.first().pk)]})
    path = object_path(record.object_key)
    with django_capture_on_commit_callbacks(execute=True):
        assert ctx["client"].delete(ctx["url"]).status_code == 204
    assert not path.exists() and Document.objects.count() == 1 and Todo.objects.count() == 1


def test_target_permissions_block_writes(ctx):
    record = ready(ctx)
    for slug in ("documents", "ideas-todos"):
        app = ctx["apps"][slug]
        app.is_active = False
        app.save()
    assert post(ctx, "/documents", {"kind": "minutes", "version": 1}).status_code == 404
    assert post(ctx, "/confirm-actions", {"version": 1, "confirmed": True, "action_ids": [str(record.actions.first().pk)]}).status_code == 404
    assert Document.objects.count() == Todo.objects.count() == 0


def test_confirmation_requires_the_exact_action_the_user_reviewed(ctx):
    record = ready(ctx)
    action = record.actions.first()
    revision = action_revision(action)
    action.title = "来自另一个标签页的修改"
    action.save()
    response = post(ctx, "/confirm-actions", {"version": 1, "confirmed": True, "action_ids": [str(action.pk)],
        "action_versions": {str(action.pk): revision}})
    assert response.status_code == 409 and Todo.objects.count() == 0


def test_cancel_queue_and_retry(ctx):
    assert post(ctx, "/runs", {"version": 1}).status_code == 409
    response = post(ctx, "/cancel")
    assert response.status_code == 200
    assert response.data["status"] in ("cancelled", "cancelling")
    response = post(ctx, "/runs", {"version": 1, "operation": "process"}, key="retry")
    assert response.status_code == 202, response.data
    replay = post(ctx, "/runs", {"version": 1, "operation": "process"}, key="retry")
    assert replay.status_code == 202 and replay.data["id"] == response.data["id"]


def test_expired_audio_token_and_removed_membership(ctx, monkeypatch):
    import time
    token = post(ctx, "/access").data["token"]
    url = ctx["root"] + "/content?token=" + token
    with monkeypatch.context() as clock:
        now = time.time()
        clock.setattr(time, "time", lambda: now + 3601)
        assert APIClient().get(url).status_code == 403
    Membership.objects.filter(organization=ctx["org"], user=ctx["owner"]).update(is_active=False)
    assert APIClient().get(url).status_code == 403


def test_edit_rejects_forged_segments_and_confirm_rejects_foreign_ids(ctx):
    ready(ctx)
    body = {"version": 1, "segments": [{"id": "invented", "text": "伪造"}]}
    assert ctx["client"].patch(ctx["url"] + "/transcript", body, format="json").status_code == 400
    response = post(ctx, "/confirm-actions", {"version": 1, "confirmed": True, "action_ids": ["de3d36d8-ae60-4bbb-881e-54d8007e0581"]})
    assert response.status_code == 400 and Todo.objects.count() == 0


def test_queued_delete_cancels_run_and_denies_history(ctx, django_capture_on_commit_callbacks):
    run = ctx["record"].active_run
    with django_capture_on_commit_callbacks(execute=True):
        assert ctx["client"].delete(ctx["url"]).status_code == 204
    run.refresh_from_db()
    assert run.status == "cancelled"
    assert ctx["client"].get(f"/api/v1/organizations/{ctx['org'].pk}/runs/{run.pk}").status_code == 404


def test_transcript_edits_block_while_running(ctx):
    response = ctx["client"].patch(ctx["url"] + "/transcript", {"version": 1, "segments": [{"id": "s1", "text": "修改"}]}, format="json")
    assert response.status_code == 409


def test_reanalysis_preserves_confirmed_action_after_correction(ctx, monkeypatch):
    record = ready(ctx)
    action = record.actions.first()
    assert post(ctx, "/confirm-actions", {"version": 1, "confirmed": True, "action_ids": [str(action.pk)]}).status_code == 200
    ctx["client"].patch(ctx["url"] + "/transcript", {"version": 1, "segments": [{"id": "s2", "text": "用户反馈尤其重要"}]}, format="json")
    assert post(ctx, "/runs", {"version": 2, "operation": "analyze"}).status_code == 202
    ctx["record"].refresh_from_db()
    payload, sink = claim(ctx)
    monkeypatch.setattr("app_center.meeting_assistant.runtime.analyze", lambda *a, **k: analysis_data())
    execute_meeting(payload, sink)
    action.refresh_from_db()
    assert action.analysis_version == 2 and action.confirmed_at and Todo.objects.count() == 1


def test_cancellation_during_analysis_does_not_publish_partial_results(ctx, monkeypatch):
    payload, sink = claim(ctx)
    monkeypatch.setattr("app_center.meeting_assistant.runtime.transcribe_segments", lambda *a, **k: {"segments": segments()})
    def cancel_during_analysis(*args, **kwargs):
        sink.cancelled = True
        return analysis_data()
    monkeypatch.setattr("app_center.meeting_assistant.runtime.analyze", cancel_during_analysis)
    with pytest.raises(InterruptedError):
        execute_meeting(payload, sink)
    ctx["record"].refresh_from_db()
    assert ctx["record"].segments and not ctx["record"].analysis and not ctx["record"].actions.exists()


def test_runtime_saves_transcript_before_analysis_and_no_todos(ctx, monkeypatch):
    payload, sink = claim(ctx)
    monkeypatch.setattr("app_center.meeting_assistant.runtime.transcribe_segments", lambda *a, **k: {"segments": segments()})
    def inspect(record, **kwargs):
        assert Recording.objects.get(pk=record.pk).segments
        return analysis_data()
    monkeypatch.setattr("app_center.meeting_assistant.runtime.analyze", inspect)
    result = execute_meeting(payload, sink)
    record = Recording.objects.get(pk=ctx["record"].pk)
    assert result["version"] == 1 and record.stage == "completed"
    assert record.actions.count() == 1 and record.analysis_version == record.version
    assert Todo.objects.count() == 0 and Document.objects.count() == 0


def test_analysis_failure_preserves_transcript_and_retry_skips_whisper(ctx, monkeypatch):
    payload, sink = claim(ctx)
    transcribe = Mock(return_value={"segments": segments()})
    monkeypatch.setattr("app_center.meeting_assistant.runtime.transcribe_segments", transcribe)
    monkeypatch.setattr("app_center.meeting_assistant.runtime.analyze", Mock(side_effect=ValueError("bad references")))
    with pytest.raises(ValueError):
        execute_meeting(payload, sink)
    record = Recording.objects.get(pk=ctx["record"].pk)
    assert record.segments and record.analysis_version == 0 and record.stage == "failed"
    monkeypatch.setattr("app_center.meeting_assistant.runtime.analyze", lambda *a, **k: analysis_data())
    execute_meeting(payload, sink)
    assert transcribe.call_count == 1


@pytest.mark.parametrize("fence", ["cancel", "version", "lease", "delete", "owner"])
def test_runtime_fences_stale_or_unauthorized_work(ctx, monkeypatch, fence):
    payload, sink = claim(ctx)
    if fence == "cancel":
        sink.cancelled = True
    elif fence == "version":
        Recording.objects.filter(pk=ctx["record"].pk).update(version=2)
    elif fence == "lease":
        RunLease.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    elif fence == "delete":
        ctx["record"].delete()
    else:
        Run.objects.filter(pk=payload["run_id"]).update(owner=ctx["reader"])
    transcribe = Mock()
    monkeypatch.setattr("app_center.meeting_assistant.runtime.transcribe_segments", transcribe)
    with pytest.raises((InterruptedError, PermissionError)):
        execute_meeting(payload, sink)
    transcribe.assert_not_called()


def test_no_speech_is_not_success(ctx, monkeypatch):
    payload, sink = claim(ctx)
    monkeypatch.setattr("app_center.meeting_assistant.runtime.transcribe_segments", lambda *a, **k: {"segments": []})
    with pytest.raises(ValueError, match="未识别到语音"):
        execute_meeting(payload, sink)
    assert Recording.objects.get(pk=ctx["record"].pk).analysis_version == 0


def test_analysis_references_quotes_dates_and_chunking():
    data = analysis_data()
    data["quotes"] = [{"text": "用户反馈非常重要", "segment_ids": ["s2"]}]
    assert validate_analysis(data, segments(), "interview")["quotes"]
    data["actions"][0]["due_date"] = "2026-09-25"
    assert validate_analysis(data, segments(), "interview")["actions"][0]["due_date"] is None
    bad = copy.deepcopy(data)
    bad["quotes"][0]["text"] = "编造原话"
    with pytest.raises(ValueError, match="原话"):
        validate_analysis(bad, segments(), "interview")
    bad["quotes"] = []
    bad["topics"][0]["segment_ids"] = ["missing"]
    with pytest.raises(ValueError, match="引用"):
        validate_analysis(bad, segments(), "interview")
    source = [{"id": f"s{i}", "text": "文" * 2000} for i in range(50)]
    batches = list(chunks(source))
    assert len(batches) > 1 and [s for batch in batches for s in batch] == source


def test_model_repair_and_reduction(ctx, monkeypatch):
    record = ready(ctx)
    engine = Mock()
    engine.complete.side_effect = [SimpleNamespace(success=True, input_request=None, content='{}'),
        SimpleNamespace(success=True, input_request=None, content=json.dumps(analysis_data()))]
    monkeypatch.setattr("app_center.meeting_assistant.backend.analysis.build_agent_engine", lambda **k: engine)
    output = analyze(record, cancelled=lambda: False, progress=Mock())
    assert output["actions"][0]["title"] == "准备材料" and engine.complete.call_count == 2


def test_shared_transcription_keeps_legacy_text_contract(monkeypatch):
    from core import transcription
    model = Mock()
    model.transcribe.return_value = (iter([SimpleNamespace(text=" Hello", start=0, end=1), SimpleNamespace(text=" ", start=1, end=1.1), SimpleNamespace(text="world ", start=1.1, end=2)]), SimpleNamespace(duration=2, language="en"))
    monkeypatch.setattr(transcription, "whisper_model", lambda name: model)
    from app_center.creation_toolbox.backend.services import transcribe_audio
    assert transcribe_audio("test.wav", "en-US") == "Hello world"
    assert model.transcribe.call_args.kwargs["language"] == "en"

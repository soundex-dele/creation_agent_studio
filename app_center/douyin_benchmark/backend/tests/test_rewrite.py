import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from .test_douyin import ctx, claim, add_work, post
from .. import analysis, media
from ..models import Task, Work
from ..serializers import TaskInput
from ... import runtime


def completed_source(ctx, work, text="原文事实。", kind="transcribe", key="source"):
    response = post(ctx, {"kind": kind, "work_id": str(work.pk)}, key)
    assert response.status_code == 201, response.data
    task = Task.objects.get(pk=response.data["id"])
    task.output = {"segments": [{"id": "s1", "text": text, "start": 0, "end": 2}]} if text else {"segments": []}
    task.save()
    task.run.status = "succeeded"
    task.run.save()
    return task


def rewrite_body(work, source):
    return {"kind": "rewrite", "work_id": str(work.pk), "source_task_id": str(source.pk),
            "source_text": "校正后的事实。", "rewrite_requirements": "更自然"}


def test_copy_defaults_do_not_change_existing_task_idempotency_payloads():
    legacy = TaskInput(data={"kind": "collect"})
    assert legacy.is_valid(), legacy.errors
    assert not {"force", "source_text", "rewrite_requirements"} & legacy.validated_data.keys()


@pytest.mark.parametrize("kind", ["transcribe", "breakdown"])
def test_reuses_latest_nonempty_successful_transcript_without_model_or_media(ctx, monkeypatch, kind):
    work = add_work(ctx)
    source = completed_source(ctx, work, kind=kind)
    completed_source(ctx, work, text="", key="empty")
    response = post(ctx, {"kind": "transcribe", "work_id": str(work.pk)}, "reuse")
    task = Task.objects.get(pk=response.data["id"])
    assert task.input["source_task_id"] == str(source.pk)
    download = Mock(side_effect=AssertionError("must reuse"))
    monkeypatch.setattr(runtime.media, "download_video", download)
    model = Mock(side_effect=AssertionError("no analysis"))
    monkeypatch.setattr(runtime.analysis, "call_model", model)
    runtime.execute(*claim(task))
    task.refresh_from_db()
    assert task.output["text"] == "原文事实。"
    download.assert_not_called()
    model.assert_not_called()
    forced = Task.objects.get(pk=post(ctx, {"kind": "transcribe", "work_id": str(work.pk), "force": True}, "force").data["id"])
    assert "reused_transcript" not in forced.input
    work.media_key = "uploads/new/video.mp4"
    work.save()
    replacement = Task.objects.get(pk=post(ctx, {"kind": "transcribe", "work_id": str(work.pk)}, "replacement").data["id"])
    assert "reused_transcript" not in replacement.input


@pytest.mark.parametrize("text", ["识别出的口播。", ""])
def test_audio_only_transcription_and_empty_text_can_be_corrected(ctx, monkeypatch, text):
    work = add_work(ctx)
    work.media_key = "uploads/test/source.mp4"
    work.save()
    task = Task.objects.get(pk=post(ctx, {"kind": "transcribe", "work_id": str(work.pk)}).data["id"])
    audio = Mock(return_value=(Path("audio.wav"), 10))
    frames = Mock(side_effect=AssertionError("no frames"))
    model = Mock(side_effect=AssertionError("no model"))
    monkeypatch.setattr(runtime.media, "extract_audio", audio)
    monkeypatch.setattr(runtime.media, "extract", frames)
    monkeypatch.setattr(runtime.analysis, "call_model", model)
    monkeypatch.setattr(runtime, "transcribe_segments", Mock(return_value={"text": text, "segments": []}))
    runtime.execute(*claim(task))
    task.refresh_from_db()
    assert task.output["text"] == text
    if not text:
        assert "手工补全" in task.output["transcript_note"]
    frames.assert_not_called()
    model.assert_not_called()
    task.run.status = "succeeded"
    task.run.save()
    assert post(ctx, rewrite_body(work, task), "rewrite").status_code == 201


def test_rewrite_freezes_input_versions_export_idempotency_and_private_access(ctx, monkeypatch):
    work = add_work(ctx)
    source = completed_source(ctx, work)
    body = rewrite_body(work, source)
    response = post(ctx, body, "rewrite")
    assert response.status_code == 201, response.data
    task = Task.objects.get(pk=response.data["id"])
    assert post(ctx, body, "rewrite").data["id"] == str(task.pk)
    assert post(ctx, {**body, "source_text": "另一个原文"}, "rewrite").status_code == 409
    source.output["segments"][0]["text"] = "随后修改"
    source.save()
    task.refresh_from_db()
    assert task.input["source_text"] == body["source_text"]
    assert set(task.run.input) == {"task_id"}
    model = Mock(return_value={"text": "新的口语表达。"})
    monkeypatch.setattr(runtime.analysis, "call_model", model)
    runtime.execute(*claim(task))
    assert model.call_args.args[2] == {"source_text": body["source_text"], "rewrite_requirements": "更自然"}
    task.refresh_from_db()
    assert task.output == {"text": "新的口语表达。"}
    assert task.versions.get().content == task.output
    task.run.status = "succeeded"
    task.run.save()
    url = f"{ctx.url}/tasks/{task.pk}"
    context = ctx.client.get(url).data["copy_context"]
    assert context["source_text"] == body["source_text"]
    assert "media_urls" not in context
    updated = ctx.client.post(url + "/versions", {"revision": 1, "content": {"text": "手工修改。"}}, format="json")
    assert updated.status_code == 201, updated.data
    conflict = ctx.client.post(url + "/versions", {"revision": 1, "content": {"text": "冲突。"}}, format="json")
    assert conflict.status_code == 409
    exported = ctx.client.get(url + f'/versions/{updated.data["id"]}/download')
    assert exported.content.decode() == "手工修改。"
    assert task.versions.count() == 2
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url).status_code == 404
    assert ctx.client.get(url + "/versions").status_code == 404
    assert ctx.client.get(url + f'/versions/{updated.data["id"]}/download').status_code == 404


def test_rewrite_rejects_wrong_work_source_state_and_invalid_inputs(ctx):
    work = add_work(ctx)
    source = completed_source(ctx, work)
    body = rewrite_body(work, source)
    other = Work.objects.create(account=ctx.account, platform_id="other", metadata={"kind": "video"})
    assert post(ctx, {**body, "work_id": str(other.pk)}).status_code == 404
    source.run.status = "failed"
    source.run.save()
    assert post(ctx, body).status_code == 404
    for changes in ({"source_text": " "}, {"source_text": "x" * 20001}, {"rewrite_requirements": "x" * 3001}, {"source_task_id": None}):
        assert post(ctx, {**body, **changes}).status_code == 400
    work.metadata["kind"] = "image_album"
    work.save()
    assert post(ctx, {"kind": "transcribe", "work_id": str(work.pk)}).status_code == 400


@pytest.mark.parametrize("value", [None, [], {}, {"text": " "}, {"text": 1}, {"text": "x" * 20001}])
def test_invalid_rewrite_output(value):
    with pytest.raises(ValueError, match="非空正文"):
        analysis.validate_rewrite(value)


def test_no_audio_track_has_actionable_error(monkeypatch):
    monkeypatch.setattr(media, "command", Mock(return_value=json.dumps({"format": {"duration": "10"}, "streams": [{"codec_type": "video"}]})))
    with pytest.raises(ValueError, match="没有音轨"):
        media.extract_audio(Path("video.mp4"), "tasks/test", lambda: None)


def test_download_failure_and_cancel_preserve_tasks(ctx, monkeypatch):
    work = add_work(ctx)
    task = Task.objects.get(pk=post(ctx, {"kind": "transcribe", "work_id": str(work.pk)}).data["id"])
    monkeypatch.setattr(runtime, "DTKClient", Mock())
    monkeypatch.setattr(runtime.media, "download_video", Mock(side_effect=ValueError("视频获取失败，请补传原视频。")))
    payload, sink = claim(task)
    with pytest.raises(RuntimeError, match="视频获取失败"):
        runtime.execute(payload, sink)
    task.refresh_from_db()
    assert "补传" in task.error
    sink.cancelled = True
    with pytest.raises(InterruptedError):
        runtime.execute(payload, sink)


@pytest.mark.parametrize("failure", ["error", "invalid", "cancel"])
def test_rewrite_failure_or_cancel_does_not_create_versions(ctx, monkeypatch, failure):
    work = add_work(ctx)
    source = completed_source(ctx, work)
    task = Task.objects.get(pk=post(ctx, rewrite_body(work, source), "rewrite").data["id"])
    payload, sink = claim(task)
    def model(*args, **kwargs):
        if failure == "error":
            raise ValueError("模型请求失败")
        if failure == "cancel":
            sink.cancelled = True
        return {"text": "结果" if failure == "cancel" else ""}
    monkeypatch.setattr(runtime.analysis, "call_model", model)
    with pytest.raises(InterruptedError if failure == "cancel" else RuntimeError):
        runtime.execute(payload, sink)
    assert not task.versions.exists()
    source.refresh_from_db()
    assert source.output["segments"][0]["text"] == "原文事实。"

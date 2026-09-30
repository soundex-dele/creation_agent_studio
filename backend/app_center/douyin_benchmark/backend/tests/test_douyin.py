import copy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import yaml
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from modules.catalog.models import ApplicationRevision, ApplicationDeployment
from modules.catalog.services import canonical_content_hash
from modules.execution.models import Run, RunAttempt, RunLease
from ..models import Account, Work, Task, Snapshot, ScriptVersion
from ..provider import source_url, normalize_work, DTKClient, CollectionError
from ..scoring import rank
from ..analysis import validate_claims, validate_topics, validate_script
from ..media import frame_times, path_for
from ...runtime import execute


def content(index=1, likes=10):
    return {"platform": "douyin", "content_id": str(7300000000000000000 + index), "kind": "video", "title": f"知识口播 {index}",
            "description": "这是测试接口样本", "created_at": (timezone.now() - timedelta(days=3)).isoformat(),
            "duration_ms": 60000, "stats": {"digg_count": likes}, "media": {"covers": []}}


def script():
    return {"title": "新的表达", "cover": "从问题开始", "narration": "今天谈一个问题。", "scenes": [{"time": "0–5秒", "visual": "固定机位", "spoken": "今天谈一个问题。"}], "checklist": ["准备提词器"]}


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.DOUYIN_MEDIA_ROOT = tmp_path / "media"
    owner = get_user_model().objects.create_user(username="dy-owner")
    reader = get_user_model().objects.create_user(username="dy-reader")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=reader, role=Membership.Role.ADMIN)
    category, _ = ApplicationCategory.objects.get_or_create(slug="dy-test", defaults={"name": "测试"})
    app = Application.objects.create(organization=org, category=category, name="抖音", slug="douyin-benchmark", created_by=owner, kind="custom", visibility="organization")
    definition = yaml.safe_load((Path(__file__).parents[2] / "application.yaml").read_text())["spec"]["definition"]
    revision = ApplicationRevision.objects.create(organization=org, application=app, revision_no=1, content=definition, content_hash=canonical_content_hash(definition), created_by=owner)
    ApplicationDeployment.objects.create(organization=org, application=app, revision=revision, updated_by=owner)
    client = APIClient(); client.force_authenticate(owner)
    root = f"/api/v1/organizations/{org.pk}/applications/{app.pk}/douyin-benchmark"
    response = client.post(root + "/accounts", {"source": "https://www.douyin.com/user/TEST"}, format="json", HTTP_IDEMPOTENCY_KEY="add-1")
    assert response.status_code == 201, response.data
    account = Account.objects.get(pk=response.data["id"])
    return SimpleNamespace(client=client, owner=owner, reader=reader, org=org, app=app, account=account, root=root, url=f"{root}/accounts/{account.pk}", task=account.tasks.first())


def claim(task):
    run = task.run
    attempt = RunAttempt.objects.create(run=run, attempt_no=1, worker_pool="media", status="running")
    RunLease.objects.create(attempt=attempt, worker_id="test", epoch=1, heartbeat_at=timezone.now(), expires_at=timezone.now() + timedelta(minutes=5))
    run.status = "running"; run.current_attempt = attempt; run.save()
    return {"run_id": str(run.pk), "attempt_id": str(attempt.pk), "organization_id": str(run.organization_id), "input": run.input}, SimpleNamespace(cancelled=False, emit=Mock())


def add_work(ctx, likes=10):
    item = normalize_work(content(likes=likes))
    work = Work.objects.create(account=ctx.account, platform_id=item["platform_id"], metadata=item)
    Snapshot.objects.create(batch=ctx.task, work=work, data=item, captured_at=timezone.now())
    return work


def post(ctx, body, key="task-2"):
    return ctx.client.post(ctx.url + "/tasks", body, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_share_url_validation():
    assert source_url("分享 https://www.douyin.com/user/MS4wTEST?x=1 快来看看") == "https://www.douyin.com/user/MS4wTEST/"
    assert source_url("https://v.douyin.com/ABC/") == "https://v.douyin.com/ABC/"
    for value in ["https://evil.test/user/a", "https://www.douyin.com@evil.test/user/a", "http://www.douyin.com/user/a", "https://www.douyin.com/video/123"]:
        with pytest.raises(ValueError): source_url(value)


def test_missing_metrics_and_milliseconds():
    result = normalize_work(content(likes=0))
    assert result["likes"] == 0 and result["comments"] is None and result["plays"] is None
    assert result["duration"] == 60


def test_scoring_filters_new_missing_and_zero():
    items = [normalize_work(content(i, 10)) for i in range(10)]
    items[-1]["likes"] = 30
    result = rank(items, timezone.now())
    assert result["items"][-1]["ratio"] == 3 and result["items"][-1]["outstanding"]
    items[0]["published_at"] = timezone.now().isoformat()
    assert rank(items, timezone.now())["items"][-1]["ratio"] is None
    for item in items: item["likes"] = 0; item["published_at"] = (timezone.now() - timedelta(days=3)).isoformat()
    assert rank(items, timezone.now())["median_likes"] == 0
    assert rank(items, timezone.now())["items"][0]["ratio"] is None


def test_page_dedup_and_loop(monkeypatch, settings):
    settings.DOUYIN_DTK_URL = "http://localhost:9999"; settings.DOUYIN_DTK_KEY = "secret"
    monkeypatch.setattr("app_center.douyin_benchmark.backend.provider.time.sleep", lambda _: None)
    client = DTKClient()
    client.fetch = Mock(side_effect=[{"items": [content(1), content(1)], "cursor": "same", "has_more": True}, {"items": [content(1), content(2)], "cursor": "same", "has_more": True}])
    gen = client.pages("author", 50)
    assert len(next(gen)[0]) == 1
    assert len(next(gen)[0]) == 1
    with pytest.raises(CollectionError, match="分页"): next(gen)


def test_async_dtk_envelope(monkeypatch, settings):
    settings.DOUYIN_DTK_URL = "http://localhost"; settings.DOUYIN_DTK_KEY = "secret"
    monkeypatch.setattr("app_center.douyin_benchmark.backend.provider.time.sleep", lambda _: None)
    client = DTKClient(); client.request = Mock(side_effect=[{"task_id": "1", "state": "queued"}, {"task_id": "1", "state": "done", "data": {"uid": "author"}}])
    assert client.fetch("/profile", {}) == {"uid": "author"}


def test_reference_validation_and_frames():
    with pytest.raises(ValueError): validate_claims({"claims": [{"type": "observation", "text": "凭空推测", "refs": ["missing"]}]}, {"s1"})
    with pytest.raises(ValueError): validate_claims({"claims": [{"type": "observation", "text": "画面", "refs": ["s1"]}]}, {"s1"}, visual=True)
    assert len(frame_times(600)) <= 16 and frame_times(600)[:4] == [0, 1, 2, 3]
    assert all(0 <= i < .5 for i in frame_times(.5))
    with pytest.raises(ValueError): path_for("../../secret")
    assert validate_script(script()) == script()
    with pytest.raises(ValueError): validate_topics({"topics": []})


def test_private_access_and_run(ctx):
    assert set(ctx.task.run.input) == {"task_id"}
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.root + "/accounts").data["count"] == 0
    assert ctx.client.get(ctx.url).status_code == 404
    assert ctx.client.get(f"/api/v1/organizations/{ctx.org.pk}/runs/{ctx.task.run_id}").status_code == 404
    ctx.client.force_authenticate(ctx.owner)
    ctx.app.is_active = False; ctx.app.save()
    assert ctx.client.get(ctx.url).status_code == 404


def test_add_idempotency_and_refresh_conflict(ctx):
    same = ctx.client.post(ctx.root + "/accounts", {"source": "https://www.douyin.com/user/TEST"}, format="json", HTTP_IDEMPOTENCY_KEY="add-1")
    assert same.status_code == 200 and same.data["task"]["id"] == str(ctx.task.pk)
    assert post(ctx, {"kind": "collect"}).status_code == 409
    assert ctx.account.tasks.count() == 1


def test_snapshots_and_frozen_inputs(ctx):
    work = add_work(ctx)
    response = post(ctx, {"kind": "account", "batch_id": str(ctx.task.pk)})
    assert response.status_code == 201, response.data
    task = Task.objects.get(pk=response.data["id"])
    old = task.input["evidence"][0]["likes"]
    work.metadata["likes"] = 9999; work.save()
    task.refresh_from_db()
    assert task.input["evidence"][0]["likes"] == old
    items = ctx.client.get(ctx.url + "/works").data["items"]
    assert items[0]["likes"] == old and items[0]["comments"] is None


def test_partial_collection_preserved(ctx, monkeypatch):
    class Client:
        def __init__(self, **kwargs): pass
        def profile(self, url): return {"platform_id": "author", "name": "知识账号"}
        def pages(self, pid, count):
            yield [normalize_work(content())], False
            raise CollectionError("limited")
    monkeypatch.setattr("app_center.douyin_benchmark.runtime.DTKClient", Client)
    payload, sink = claim(ctx.task)
    execute(payload, sink)
    ctx.task.refresh_from_db()
    assert ctx.task.stage == "partial" and ctx.task.output["actual"] == 1
    assert ctx.task.output["complete"] is False
    assert ctx.task.snapshots.count() == 1


def test_cancelled_or_expired_attempt_cannot_write(ctx):
    payload, sink = claim(ctx.task); sink.cancelled = True
    with pytest.raises(InterruptedError): execute(payload, sink)
    assert not ctx.task.snapshots.exists()
    sink.cancelled = False
    RunLease.objects.filter(attempt_id=payload["attempt_id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(InterruptedError): execute(payload, sink)


def test_failed_new_analysis_preserves_old(ctx, monkeypatch):
    add_work(ctx)
    task = Task.objects.get(pk=post(ctx, {"kind": "account"}).data["id"])
    payload, sink = claim(task)
    monkeypatch.setattr("app_center.douyin_benchmark.runtime.analysis.call_model", Mock(side_effect=ValueError("模型失败")))
    with pytest.raises(RuntimeError, match="模型失败"): execute(payload, sink)
    assert ctx.task.snapshots.count() == 1
    task.refresh_from_db(); assert task.error == "模型失败"


def test_account_analysis_uses_system_engine_without_org_provider(ctx, monkeypatch):
    from .. import analysis
    from core.agent_engine.models import LLMResponse, TokenUsage
    from apps.enterprise.models import UsageRecord
    work = add_work(ctx)
    task = Task.objects.get(pk=post(ctx, {"kind": "account"}).data["id"])
    engine = Mock(adapter_name="codex")
    engine.complete.return_value = LLMResponse(
        content='{"claims":[{"type":"observation","text":"样本包含知识口播","refs":["' + str(work.pk) + '"]}]}',
        usage=TokenUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20), model="test-model")
    monkeypatch.setattr(analysis, "build_agent_engine", Mock(return_value=engine))
    assert not ctx.org.providers.exists()
    execute(*claim(task))
    task.refresh_from_db()
    assert task.stage == "completed" and task.error == ""
    assert task.output["statistics"]["sample_count"] == 1
    assert task.output["claims"][0]["refs"] == [str(work.pk)]
    assert UsageRecord.objects.get(resource_type="douyin_analysis", resource_id=str(task.pk)).total_tokens == 20


def test_script_versions_conflict_and_export(ctx):
    task = Task.objects.create(account=ctx.account, kind="script", request_key="script", request_hash="x", output=script())
    run = ctx.task.run; ctx.task.run = None; ctx.task.save()
    run.status = "succeeded"; run.save(); task.run = run; task.save()
    ScriptVersion.objects.create(task=task, revision=1, content=script())
    url = ctx.url + f"/tasks/{task.pk}/versions"
    updated = {**script(), "title": "第二版", "production_format": "screencast"}
    response = ctx.client.post(url, {"revision": 1, "content": updated}, format="json")
    assert response.status_code == 201, response.data
    assert ctx.client.post(url, {"revision": 1, "content": updated}, format="json").status_code == 409
    assert task.versions.count() == 2 and task.versions.last().content["title"] == "新的表达"
    download = ctx.client.get(url + f'/{response.data["id"]}/download')
    assert "第二版" in download.content.decode()
    assert response.data["content"]["production_format"] == "screencast"
    assert "视频形式：录屏演示" in download.content.decode()


def test_connection_does_not_expose_credentials(ctx, settings):
    settings.DOUYIN_DTK_URL = ""; settings.DOUYIN_DTK_KEY = "top-secret"
    response = ctx.client.get(ctx.root + "/connection")
    assert not response.data["connected"] and "top-secret" not in str(response.data)


@pytest.mark.parametrize("production_format,label", [("talking_head", "真人口播"), ("screencast", "录屏演示"), ("animation", "动画演示"), ("live_action", "实景拍摄"), ("mixed", "混合形式")])
def test_breakdown_topics_script_pipeline(ctx, monkeypatch, production_format, label):
    work = add_work(ctx)
    task = Task.objects.get(pk=post(ctx, {"kind": "breakdown", "work_id": str(work.pk)}).data["id"])
    from app_center.douyin_benchmark import runtime
    monkeypatch.setattr(runtime, "DTKClient", lambda **kw: SimpleNamespace(detail=lambda pid: {"content_id": pid, "kind": "video", "media": {"video": {"url": "https://v.douyinvod.com/media", "watermark": False}}}, media_headers=lambda: {"User-Agent": "personal-UA", "Referer": "https://www.douyin.com/"}))
    download = Mock(return_value=Path("/test/video.mp4"))
    monkeypatch.setattr(runtime.media, "download", download)
    monkeypatch.setattr(runtime.media, "extract", lambda *args: (Path("/test/audio.wav"), [{"id": "f0", "time": 0, "key": "tasks/test/f0.jpg"}], 60))
    monkeypatch.setattr(runtime, "transcribe_segments", lambda *args, **kwargs: {"segments": [{"id": "s1", "start": 0, "end": 5, "text": "先问一个问题"}]})
    model = Mock(return_value={"claims": [{"type": "observation", "text": "用问题开场", "refs": ["s1"]}]})
    monkeypatch.setattr(runtime.analysis, "call_model", model)
    execute(*claim(task))
    task.refresh_from_db()
    assert download.call_args.kwargs["headers"] == {"User-Agent": "personal-UA", "Referer": "https://www.douyin.com/"}
    assert task.output["visual_status"] == "pending"
    assert task.output["segments"][0]["id"] == "s1"
    task.run.status = "succeeded"; task.run.save()
    topics = [{"title": f"选题{i}", "angle": "换一个角度", "hook": "你有没有遇到过"} for i in range(3)]
    topic_response = post(ctx, {"kind": "topics", "source_task_id": str(task.pk), "positioning": "读书", "theme": "表达", "duration": 90, "production_format": production_format}, key="topics")
    assert topic_response.status_code == 201, topic_response.data
    topic_task = Task.objects.get(pk=topic_response.data["id"])
    model.return_value = {"topics": topics}
    execute(*claim(topic_task))
    assert label in model.call_args.args[1]
    topic_task.refresh_from_db()
    assert topic_task.output["production_format"] == production_format
    topic_task.run.status = "succeeded"; topic_task.run.save()
    response = post(ctx, {"kind": "script", "source_task_id": str(topic_task.pk), "topic_index": 2, "production_format": "live_action"}, key="script-new")
    assert response.status_code == 201, response.data
    script_task = Task.objects.get(pk=response.data["id"])
    assert script_task.input["brief"]["duration"] == 90
    assert script_task.input["brief"]["production_format"] == production_format
    assert script_task.input["topic"]["title"] == "选题2"
    model.return_value = {**script(), "production_format": "wrong-model-value"}
    execute(*claim(script_task))
    assert script_task.versions.count() == 1
    assert script_task.versions.first().content["production_format"] == production_format
    assert label in model.call_args.args[1]
    assert "key" not in str(ctx.client.get(ctx.url + f"/tasks/{task.pk}").data["output"]["frames"])


def test_visual_failure_retains_transcript(ctx, monkeypatch):
    work = add_work(ctx)
    task = Task.objects.get(pk=post(ctx, {"kind": "breakdown", "work_id": str(work.pk)}).data["id"])
    from app_center.douyin_benchmark import runtime
    monkeypatch.setattr(runtime, "DTKClient", lambda **kw: SimpleNamespace(detail=lambda pid: {"content_id": pid, "kind": "video", "media": {"video": {"url": "https://v.douyinvod.com/media", "watermark": False}}}, media_headers=lambda: {"User-Agent": "personal-UA", "Referer": "https://www.douyin.com/"}))
    download = Mock(return_value=Path("/test/video.mp4"))
    monkeypatch.setattr(runtime.media, "download", download)
    monkeypatch.setattr(runtime.media, "extract", lambda *args: (Path("/test/audio.wav"), [{"id": "f0", "time": 0, "key": "frame.jpg"}], 60))
    monkeypatch.setattr(runtime, "transcribe_segments", lambda *a, **kw: {"segments": [{"id": "s1", "start": 0, "end": 5, "text": "先问一个问题"}]})
    monkeypatch.setattr(runtime.analysis, "call_model", Mock(side_effect=[{"claims": [{"type": "observation", "text": "问题开场", "refs": ["s1"]}]}, ValueError("视觉模型不可用")]))
    payload, sink = claim(task); payload["effective_config"] = {"vision_model": "configured-vision"}
    execute(payload, sink); task.refresh_from_db()
    assert task.output["visual_status"] == "failed" and task.output["segments"]
    assert task.output["claims"][0]["refs"] == ["s1"]


def test_unknown_task_work_cross_account_is_rejected(ctx):
    second = Account.objects.create(application=ctx.app, owner=ctx.owner, organization=ctx.org, source_url="https://www.douyin.com/user/SECOND/")
    work = Work.objects.create(account=second, platform_id="123", metadata={})
    assert post(ctx, {"kind": "breakdown", "work_id": str(work.pk)}).status_code == 404
    assert post(ctx, {"kind": "topics", "source_task_id": str(ctx.task.pk), "theme": "a", "positioning": "b"}).status_code == 404


def test_refresh_retains_previous_batch_and_deduplicates(ctx, monkeypatch):
    work = add_work(ctx)
    ctx.task.run.status = "succeeded"; ctx.task.run.save()
    response = post(ctx, {"kind": "collect", "count": 20})
    task = Task.objects.get(pk=response.data["id"])
    monkeypatch.setattr("app_center.douyin_benchmark.runtime.DTKClient", lambda **kw: SimpleNamespace(
        profile=lambda url: {"platform_id": "author", "name": "读书"}, pages=lambda *args: iter([([normalize_work(content(likes=300))], True)])))
    execute(*claim(task))
    assert ctx.account.works.count() == 1 and Snapshot.objects.filter(work=work).count() == 2
    assert ctx.client.get(ctx.url + "/works", {"batch_id": str(ctx.task.pk)}).data["items"][0]["likes"] == 10
    assert ctx.client.get(ctx.url + "/works").data["items"][0]["likes"] == 300


def test_real_ffmpeg_extract_bounds(tmp_path, settings):
    import shutil
    import subprocess
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg is not installed")
    from ..media import extract, probe
    settings.DOUYIN_MEDIA_ROOT = tmp_path / "private"
    source = tmp_path / "synthetic.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=96x160:r=10:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(source)], check=True, timeout=30)
    audio, frames, duration = extract(source, "tasks/test", lambda: None)
    assert 1.9 < duration < 2.2 and audio.is_file() and 1 <= len(frames) <= 16
    assert all(path_for(f["key"]).is_file() for f in frames)
    assert all(f["time"] < duration for f in frames)


def test_model_checks_quota_and_records_actual_usage(ctx, monkeypatch):
    from .. import analysis
    quota = Mock(); usage = Mock()
    monkeypatch.setattr(analysis, "enforce_member_token_quota", quota)
    monkeypatch.setattr(analysis, "record_usage", usage)
    provider = SimpleNamespace(base_url="https://model.example/v1", timeout_seconds=10, name="test-model")
    monkeypatch.setattr(analysis, "_provider", lambda *args: (provider, "private-secret", "text-model"))
    response = Mock(); response.json.return_value = {"choices": [{"message": {"content": '{"topics":[]}'}}], "usage": {"prompt_tokens": 42, "completion_tokens": 8}}
    request = Mock(return_value=response); monkeypatch.setattr(analysis.requests, "post", request)
    assert analysis.call_model(ctx.task, "test", {"source": "test data"}, {}) == {"topics": []}
    quota.assert_called_once_with(ctx.org, ctx.owner)
    assert usage.call_args.kwargs["usage"] == {"prompt_tokens": 42, "completion_tokens": 8}
    quota.side_effect = ValueError("quota exceeded")
    with pytest.raises(ValueError): analysis.call_model(ctx.task, "test", {}, {})
    assert request.call_count == 1


def test_media_rejects_arbitrary_download_hosts():
    from ..media import checked_media_url
    for url in ("http://127.0.0.1/video", "https://evil.example/video", "file:///etc/passwd", "https://douyinvod.com.evil.example/video"):
        with pytest.raises(ValueError): checked_media_url(url)


def test_deleting_account_revokes_run_and_frame_access(ctx):
    run_id = ctx.task.run_id
    assert ctx.client.delete(ctx.url).status_code == 204
    assert not Account.objects.filter(pk=ctx.account.pk).exists()
    assert ctx.client.get(f"/api/v1/organizations/{ctx.org.pk}/runs/{run_id}").status_code == 404
    assert ctx.client.get(ctx.url + f"/tasks/{ctx.task.pk}/frames/f0").status_code == 404


def test_empty_breakdown_cannot_be_used_as_creative_evidence(monkeypatch):
    from rest_framework.exceptions import ValidationError
    from .. import services
    source = SimpleNamespace(output={"claims": []})
    monkeypatch.setattr(services, "get_object_or_404", lambda *args, **kwargs: source)
    with pytest.raises(ValidationError, match="暂无可用结论"):
        services.frozen_input(SimpleNamespace(tasks=object()), {"kind": "topics", "source_task_id": "source", "theme": "阅读", "positioning": "读书"})

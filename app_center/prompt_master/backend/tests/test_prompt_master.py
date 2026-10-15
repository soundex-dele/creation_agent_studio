import json
import shutil
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework.exceptions import Throttled
from apps.applications.models import Application, ApplicationCategory
from apps.applications.app_center.discovery import discover_packages
from apps.enterprise.models import Membership
from core.llm import application
from core.agent_engine.models import LLMResponse, TokenUsage
from unittest.mock import Mock
from modules.execution.models import Run
from app_center.prompt_master import runtime
from .. import views
from ..models import PromptSession, PromptTask, PromptVersion
from ..serializers import validate_output


class Sink:
    cancelled = False

    def emit(self, *args):
        pass


def questions(prefix="q", count=3):
    return [{"id": f"{prefix}{i}", "label": f"关键问题 {prefix}{i}", "help": "补充需求", "type": "text",
             "options": [], "recommended": "采用通用说明"} for i in range(count)]


def analysis(scene="writing", qs=None):
    return {"scene": scene, "summary": "为新手整理实用指南", "issues": [], "questions": questions() if qs is None else qs}


def output():
    return {"standard": "请为新手写指南。预算不超过2000元。用表格输出。", "concise": "写新手指南，预算不超过2000元，用表格输出。",
            "assumptions": ["采用通俗的语气"], "health": [], "changes": ["明确输出格式"],
            "constraints": [{"text": "预算限制", "standard_excerpt": "预算不超过2000元", "concise_excerpt": "预算不超过2000元"}]}


@pytest.fixture
def context(db, monkeypatch):
    owner = get_user_model().objects.create_user(username="prompt-owner")
    user = get_user_model().objects.create_user(username="prompt-user")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=user, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name="Prompt", slug="prompt-test")
    app = Application.objects.create(organization=org, category=category, name="提示词大师", slug="prompt-master",
                                     created_by=owner, kind=Application.Kind.CUSTOM, visibility=Application.Visibility.ORGANIZATION)
    client = APIClient()
    client.force_authenticate(user)

    def start(**kw):
        return Run.objects.create(organization_id=kw["organization_id"], owner=kw["actor"], source_type="application",
                                  source_id=str(kw["application_id"]), executor_kind="media", executor_key="prompt-master", input=kw["input_data"]), True

    monkeypatch.setattr(views, "start_application_run", start)
    monkeypatch.setattr(views, "submit_run_command", lambda **kw: None)
    return SimpleNamespace(client=client, owner=owner, user=user, org=org, app=app,
                           base=f"/api/v1/organizations/{org.pk}/applications/{app.pk}/prompt-master")


def create(ctx, **extra):
    result = ctx.client.post(ctx.base + "/sessions", {"topic": "新手指南，预算不超过2000元，用表格输出", **extra}, format="json")
    assert result.status_code == 201, result.data
    return result.data


def url(ctx, session):
    return ctx.base + "/sessions/" + str(session["id"])


def task(ctx, session, kind="analyze", **extra):
    response = ctx.client.post(url(ctx, session) + "/tasks", {"kind": kind, "revision": session["revision"], "request_key": str(uuid4()), **extra}, format="json")
    assert response.status_code in (200, 202), response.data
    return PromptTask.objects.select_related("run", "session__owner", "session__organization").get(pk=response.data["id"])


def execute(t):
    return runtime.execute({"run_id": str(t.run_id), "organization_id": str(t.organization_id), "input": {"task_id": str(t.pk)}}, Sink())


def complete(ctx, session, monkeypatch, kind="analyze", value=None, **extra):
    t = task(ctx, session, kind, **extra)
    monkeypatch.setattr(runtime, "call_model", lambda *_: value if value is not None else analysis())
    execute(t)
    t.refresh_from_db()
    assert t.status == "succeeded"
    return ctx.client.get(url(ctx, session)).data


@pytest.mark.parametrize("scene", ["writing", "coding", "learning", "office", "image", "video", "general"])
def test_full_flow_preserves_answers_constraints_and_versions(context, monkeypatch, scene):
    ctx = context
    session = create(ctx, scene=scene, language="en")
    session = complete(ctx, session, monkeypatch, value=analysis(scene))
    answers = {"q0": None, "q1": "自定义要求", "q2": ["选项一", "选项二"]}
    response = ctx.client.patch(url(ctx, session), {"revision": session["revision"], "answers": answers}, format="json")
    assert response.status_code == 200
    session = complete(ctx, response.data, monkeypatch, kind="generate", value=output())
    version = session["latest_version"]
    assert version["basis"]["answers"] == answers
    assert version["basis"]["language"] == "en"
    assert version["constraints"][0]["concise_excerpt"] in version["concise"]
    assert session["detected_scene"] == scene
    assert session["rounds"] == 1 and not session["results_stale"]
    assert ctx.client.get(url(ctx, session)).data["latest_task"]["status"] == "succeeded"


def test_sufficient_information_skips_questions(context, monkeypatch):
    session = complete(context, create(context), monkeypatch, value=analysis(qs=[]))
    assert session["rounds"] == 1 and session["questions"] == []
    assert complete(context, session, monkeypatch, "generate", output())["latest_version"]


def test_only_two_rounds_and_no_repeated_questions(context, monkeypatch):
    s = complete(context, create(context), monkeypatch)
    s = complete(context, s, monkeypatch, value=analysis(qs=questions("extra", 2)))
    assert len(s["questions"]) == 5 and s["rounds"] == 2
    response = context.client.post(url(context, s) + "/tasks", {"kind": "analyze", "revision": s["revision"], "request_key": "third"}, format="json")
    assert response.status_code == 400


@pytest.mark.parametrize("rounds,qs", [(0, questions(count=6)), (0, questions(count=1)), (1, questions("extra", 4)), (1, questions()), (2, [])])
def test_invalid_question_counts_and_duplicate_ids(rounds, qs):
    t = SimpleNamespace(kind="analyze", snapshot={"rounds": rounds, "questions": questions() if rounds else []})
    with pytest.raises(ValueError):
        validate_output(t, analysis(qs=qs))


def test_optimization_preserves_original_and_manual_edit_requires_new_check(context, monkeypatch):
    original = "帮我写文案，不超过200字。"
    s = create(context, mode="optimize", original=original, objective="更具体")
    s = complete(context, s, monkeypatch)
    s = complete(context, s, monkeypatch, "optimize", output())
    old = s["latest_version"]
    response = context.client.post(url(context, s) + "/versions", {"revision": s["revision"], "version_id": old["id"], "standard": "手动标准版", "concise": "手动精简版"}, format="json")
    assert response.status_code == 201
    edited = response.data
    assert edited["latest_version"]["health_stale"] is True
    checked = complete(context, edited, monkeypatch, "check", {"health": [{"problem": "缺少字数限制", "suggestion": "补回200字限制"}]}, version_id=edited["latest_version"]["id"])
    assert checked["original"] == original
    assert checked["latest_version"]["standard"] == "手动标准版"
    assert checked["latest_version"]["health_stale"] is False
    assert context.client.get(url(context, s) + "/versions").data["count"] == 3
    assert PromptVersion.objects.get(pk=old["id"]).standard == old["standard"]


def test_updates_invalidate_questions_and_results_and_reject_stale_saves(context, monkeypatch):
    s = complete(context, create(context), monkeypatch)
    s = complete(context, s, monkeypatch, "generate", output())
    changed = context.client.patch(url(context, s), {"revision": s["revision"], "topic": "写代码"}, format="json")
    assert changed.status_code == 200
    assert changed.data["rounds"] == 0 and changed.data["questions"] == [] and changed.data["answers"] == {}
    assert changed.data["results_stale"] and changed.data["latest_version"]
    assert context.client.patch(url(context, s), {"revision": s["revision"], "title": "覆盖"}, format="json").status_code == 409
    assert context.client.patch(url(context, s), {"revision": changed.data["revision"], "answers": {"q0": "失效回答"}}, format="json").status_code == 400


def test_request_idempotency_and_single_active_task(context):
    s = create(context)
    first = task(context, s, request_key="same")
    again = task(context, s, request_key="same")
    assert again.pk == first.pk and PromptTask.objects.count() == 1
    endpoint = url(context, s) + "/tasks"
    assert context.client.post(endpoint, {"kind": "analyze", "revision": 0, "request_key": "same", "instruction": "changed"}, format="json").status_code == 409
    assert context.client.post(endpoint, {"kind": "analyze", "revision": 0, "request_key": "other"}, format="json").status_code == 409


@pytest.mark.parametrize("change", ["input", "cancel", "delete", "revoke"])
def test_late_result_never_overwrites_changed_or_cancelled_session(context, monkeypatch, change):
    s = create(context)
    t = task(context, s)

    def model(*_):
        if change == "input":
            response = context.client.patch(url(context, s), {"revision": 0, "topic": "更新后的主题"}, format="json")
        elif change == "cancel":
            response = context.client.post(url(context, s) + f"/tasks/{t.pk}/cancel")
        elif change == "delete":
            response = context.client.delete(url(context, s) + "?revision=0")
        else:
            context.app.is_active = False
            context.app.save()
            return analysis()
        assert response.status_code in (200, 204)
        return analysis()

    monkeypatch.setattr(runtime, "call_model", model)
    if change == "revoke":
        with pytest.raises(RuntimeError):
            execute(t)
    else:
        execute(t)
    t.refresh_from_db()
    assert t.status == {"input": "stale", "cancel": "cancelled", "delete": "cancelled", "revoke": "failed"}[change]
    assert PromptSession.objects.get(pk=s["id"]).rounds == 0
    assert not PromptVersion.objects.exists()


def test_private_history_search_favorites_copy_and_delete(context, monkeypatch):
    s = create(context, title="我的视频", scene="video")
    saved = context.client.patch(url(context, s), {"revision": 0, "favorite": True, "title": "新标题"}, format="json").data
    assert context.client.get(context.base + "/sessions", {"search": "新", "scene": "video", "favorite": "1"}).data["count"] == 1
    assert context.client.get(context.base + "/sessions", {"search": "不存在"}).data["count"] == 0
    copied = context.client.post(url(context, s) + "/copy").data
    assert copied["topic"] == s["topic"] and copied["latest_version"] is None and not copied["favorite"]
    assert context.client.delete(url(context, s) + "?revision=0").status_code == 409
    assert context.client.delete(url(context, s) + f'?revision={saved["revision"]}').status_code == 204
    assert context.client.get(url(context, s)).status_code == 404
    context.client.force_authenticate(context.owner)
    assert context.client.get(context.base + "/sessions").data["count"] == 0
    assert context.client.get(url(context, copied)).status_code == 404
    assert context.client.post(url(context, copied) + "/copy").status_code == 404


def test_auth_tenant_and_application_boundaries(context):
    s = create(context)
    assert APIClient().get(context.base + "/catalog").status_code in (401, 403)
    foreign = context.user.owned_organizations.get()
    assert context.client.get(url(context, s).replace(str(context.org.pk), str(foreign.pk))).status_code == 404
    outsider = get_user_model().objects.create_user(username="prompt-outsider")
    context.client.force_authenticate(outsider)
    assert context.client.get(url(context, s)).status_code in (403, 404)
    context.client.force_authenticate(context.user)
    context.app.visibility = Application.Visibility.RESTRICTED
    context.app.save()
    assert context.client.get(url(context, s)).status_code == 404


@pytest.mark.parametrize("value", [None, [], {}, {"standard": "", "concise": ""}, {**output(), "constraints": [{"text": "遗漏", "standard_excerpt": "不存在", "concise_excerpt": "不存在"}]}])
def test_invalid_generation_never_saves_versions(context, monkeypatch, value):
    s = complete(context, create(context), monkeypatch)
    t = task(context, s, "generate")
    monkeypatch.setattr(runtime, "call_model", lambda *_: value)
    with pytest.raises(RuntimeError):
        execute(t)
    t.refresh_from_db()
    assert t.status == "failed" and not PromptVersion.objects.exists()


def test_platform_failure_status_is_visible_and_retry_allowed(context):
    s = create(context)
    t = task(context, s)
    t.run.status = "failed"
    t.run.save()
    detail = context.client.get(url(context, s)).data
    assert detail["latest_task"]["status"] == "failed"
    assert task(context, detail).pk != t.pk


def test_model_adapter_tracks_usage_and_keeps_inputs_as_data(context, monkeypatch):
    t = task(context, create(context))
    usage = []
    engine = Mock(adapter_name="codex")
    engine.complete.return_value = LLMResponse(content=json.dumps(analysis()), usage=TokenUsage(total_tokens=10), model="system-model")
    monkeypatch.setattr(application, "build_agent_engine", Mock(return_value=engine))
    monkeypatch.setattr(application, "enforce_member_token_quota", lambda *_: None)
    monkeypatch.setattr(application, "record_usage", lambda **kw: usage.append(kw))
    assert runtime.call_model(t, {})["questions"]
    messages = engine.complete.call_args.args[0]
    assert len(messages) == 2
    assert json.loads(messages[1]["content"])["topic"] == t.session.topic
    assert usage[0]["resource_type"] == "prompt_generation"
    assert usage[0]["provider"] == "codex"


@pytest.mark.parametrize("failure", ["engine", "quota", "timeout", "json", "input", "failed"])
def test_model_failures_remain_retryable_without_fake_results(context, monkeypatch, failure):
    t = task(context, create(context))
    engine = Mock(adapter_name="codex")
    engine.complete.return_value = LLMResponse(content=json.dumps(analysis()), usage=TokenUsage(), model="system-model")
    factory = Mock(return_value=engine)
    quota = Mock()
    monkeypatch.setattr(application, "build_agent_engine", factory)
    monkeypatch.setattr(application, "enforce_member_token_quota", quota)
    monkeypatch.setattr(application, "record_usage", lambda **kw: None)
    if failure == "engine":
        factory.side_effect = RuntimeError("private engine details")
    elif failure == "quota":
        quota.side_effect = Throttled()
    elif failure == "timeout":
        engine.complete.side_effect = TimeoutError()
    elif failure == "json":
        engine.complete.return_value.content = "invalid JSON"
    elif failure == "input":
        engine.complete.return_value.input_request = {"question": "confirm"}
    else:
        engine.complete.return_value.success = False
    with pytest.raises(RuntimeError):
        execute(t)
    t.refresh_from_db()
    assert t.status == "failed" and t.error
    assert "private" not in t.error
    assert not PromptVersion.objects.exists()


def test_catalog_has_two_templates_per_scene(context):
    data = context.client.get(context.base + "/catalog").data
    assert len(data["templates"]) == 12
    for scene in ["writing", "coding", "learning", "office", "image", "video"]:
        assert len([t for t in data["templates"] if t["scene"] == scene]) == 2


def test_checking_old_version_does_not_make_it_current(context, monkeypatch):
    s = complete(context, create(context), monkeypatch)
    s = complete(context, s, monkeypatch, "generate", output())
    old = s["latest_version"]
    s = context.client.patch(url(context, s), {"revision": s["revision"], "topic": "全新的主题"}, format="json").data
    s = complete(context, s, monkeypatch)
    s = complete(context, s, monkeypatch, "generate", output())
    assert not s["results_stale"]
    checked = complete(context, s, monkeypatch, "check", {"health": []}, version_id=old["id"])
    assert checked["results_stale"]


def test_terminated_run_cannot_apply_a_late_response(context, monkeypatch):
    s = create(context)
    t = task(context, s)

    def model(*_):
        Run.objects.filter(pk=t.run_id).update(status="failed")
        return analysis()

    monkeypatch.setattr(runtime, "call_model", model)
    execute(t)
    t.refresh_from_db()
    assert t.status == "failed"
    assert PromptSession.objects.get(pk=s["id"]).rounds == 0


def test_conflicting_constraints_remain_visible_in_analysis_and_assumptions(context, monkeypatch):
    s = create(context, topic="只输出一句话，同时至少写十段正文")
    value = analysis()
    value["issues"] = [{"problem": "一句话与十段正文冲突", "suggestion": "请选择优先要求"}]
    s = complete(context, s, monkeypatch, value=value)
    assert s["analysis"]["issues"][0]["problem"]
    value = output()
    value["assumptions"] = ["用户未选择优先项，暂按一句话输出；十段要求未满足"]
    s = complete(context, s, monkeypatch, "generate", value)
    assert "未满足" in s["latest_version"]["assumptions"][0]


@pytest.mark.django_db
def test_package_is_discoverable_and_install_is_idempotent(tmp_path, settings):
    shutil.copytree(settings.APP_CENTER_ROOT / "prompt_master", tmp_path / "prompt_master")
    settings.APP_CENTER_ROOT = tmp_path
    packages, errors = discover_packages(tmp_path, strict=True)
    assert not errors and packages[0].manifest.metadata.id == "prompt-master"
    owner = get_user_model().objects.create_user(username="prompt-install")
    org = owner.owned_organizations.get()
    for _ in range(2):
        call_command("sync_app_center", package_id="prompt-master", organization_id=str(org.pk))
    app = Application.objects.get(organization=org, slug="prompt-master")
    assert app.is_active and app.revisions.count() == 1 and app.deployments.count() == 1
    assert app.draft.content["renderer_key"] == "prompt-master"

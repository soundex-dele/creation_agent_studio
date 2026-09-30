from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from core.agent_engine.models import LLMResponse, TokenUsage
from .. import analysis


@pytest.fixture
def context(monkeypatch):
    organization = SimpleNamespace(providers=Mock())
    organization.providers.exists.return_value = False
    task = SimpleNamespace(id="task", account=SimpleNamespace(organization=organization, owner=object()))
    route = Mock(side_effect=analysis.ProviderUnavailable())
    engine = Mock(adapter_name="codex")
    engine.complete.return_value = LLMResponse(content='```json\n{"claims": []}\n```',
        usage=TokenUsage(prompt_tokens=42, completion_tokens=8, total_tokens=50), model="configured-model")
    factory = Mock(return_value=engine)
    quota, usage, request = Mock(), Mock(), Mock()
    for name, value in (("_provider", route), ("build_agent_engine", factory),
                        ("enforce_member_token_quota", quota), ("record_usage", usage)):
        monkeypatch.setattr(analysis, name, value)
    monkeypatch.setattr(analysis.requests, "post", request)
    return SimpleNamespace(task=task, route=route, engine=engine, factory=factory,
                           quota=quota, usage=usage, request=request)


def test_unconfigured_text_uses_system_engine_and_records_usage(context):
    cancelled = Mock(return_value=False)
    assert analysis.call_model(context.task, "分析账号", {"works": []}, {}, cancelled=cancelled) == {"claims": []}
    context.quota.assert_called_once_with(context.task.account.organization, context.task.account.owner)
    context.request.assert_not_called()
    assert context.factory.call_args.args == (context.task.account.organization,)
    assert not Path(context.factory.call_args.kwargs["working_directory"]).exists()
    options = context.engine.complete.call_args.kwargs
    assert options["cancelled"] is cancelled and options["permission_mode"] == "default"
    assert context.usage.call_args.kwargs["usage"]["total_tokens"] == 50
    assert context.usage.call_args.kwargs["provider"] == "codex"
    assert context.usage.call_args.kwargs["model"] == "configured-model"


@pytest.mark.parametrize("config,frames,has_providers", [
    ({"answer_provider": "missing"}, None, False),
    ({"answer_model": "missing-model"}, None, False),
    ({}, [], False),
    ({}, None, True),
])
def test_explicit_api_routes_vision_and_disabled_providers_do_not_fallback(context, config, frames, has_providers):
    context.task.account.organization.providers.exists.return_value = has_providers
    with pytest.raises(ValueError, match="组织设置"):
        analysis.call_model(context.task, "test", {}, config, frames=frames)
    context.factory.assert_not_called()


def test_organization_provider_keeps_priority_and_request_failures_do_not_fallback(context):
    context.route.side_effect = None
    context.route.return_value = (SimpleNamespace(base_url="https://model.example/v1", name="org-model", timeout_seconds=30), "key", "text-model")
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": '{"claims": []}'}}], "usage": {"total_tokens": 7}}
    context.request.return_value = response
    assert analysis.call_model(context.task, "test", {}, {}) == {"claims": []}
    assert context.usage.call_args.kwargs["provider"] == "org-model"
    context.request.side_effect = requests.RequestException("private upstream details")
    with pytest.raises(ValueError, match="模型请求失败") as exc:
        analysis.call_model(context.task, "test", {}, {})
    assert "private" not in str(exc.value)
    context.factory.assert_not_called()


@pytest.mark.parametrize("mode", ["exception", "failed", "input"])
def test_engine_failure_is_safe_and_never_retried(context, mode):
    if mode == "exception":
        context.engine.complete.side_effect = RuntimeError("private token and upstream body")
    elif mode == "failed":
        context.engine.complete.return_value.success = False
        context.engine.complete.return_value.error = "private token and upstream body"
    else:
        context.engine.complete.return_value.input_request = {"question": "private question"}
    with pytest.raises(ValueError, match="系统模型引擎") as exc:
        analysis.call_model(context.task, "test", {}, {})
    assert "private" not in str(exc.value)
    assert context.engine.complete.call_count == 1


@pytest.mark.parametrize("raw", ["[]", "not json", "```broken"])
def test_invalid_engine_json_is_rejected_and_usage_kept(context, raw):
    context.engine.complete.return_value.content = raw
    with pytest.raises(ValueError, match="结构化"):
        analysis.call_model(context.task, "test", {}, {})
    context.usage.assert_called_once()


def test_quota_and_input_limits_prevent_engine_calls(context):
    context.quota.side_effect = ValueError("quota exceeded")
    with pytest.raises(ValueError, match="quota"):
        analysis.call_model(context.task, "test", {}, {})
    context.quota.side_effect = None
    with pytest.raises(ValueError, match="上限"):
        analysis.call_model(context.task, "test", {"text": "x" * 180001}, {})
    context.factory.assert_not_called()


def test_cancelled_job_does_not_generate_or_accept_results(context):
    with pytest.raises(InterruptedError):
        analysis.call_model(context.task, "test", {}, {}, cancelled=lambda: True)
    context.factory.assert_not_called()
    cancelled = Mock(side_effect=[False, True])
    with pytest.raises(InterruptedError):
        analysis.call_model(context.task, "test", {}, {}, cancelled=cancelled)
    context.usage.assert_not_called()

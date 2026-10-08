from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm import application
from .. import analysis


@pytest.fixture
def context(monkeypatch):
    organization = SimpleNamespace(providers=Mock())
    organization.providers.exists.return_value = False
    task = SimpleNamespace(id="task", organization=organization, owner=object())
    engine = Mock(adapter_name="codex")
    engine.complete.return_value = LLMResponse(content='```json\n{"claims": []}\n```',
        usage=TokenUsage(prompt_tokens=42, completion_tokens=8, total_tokens=50), model="configured-model")
    factory = Mock(return_value=engine)
    quota, usage = Mock(), Mock()
    for name, value in (("build_agent_engine", factory),
                        ("enforce_member_token_quota", quota), ("record_usage", usage)):
        monkeypatch.setattr(application, name, value)
    return SimpleNamespace(task=task, engine=engine, factory=factory,
                           quota=quota, usage=usage)


def test_unconfigured_text_uses_system_engine_and_records_usage(context):
    cancelled = Mock(return_value=False)
    assert analysis.call_model(context.task, "分析账号", {"works": []}, {}, cancelled=cancelled) == {"claims": []}
    context.quota.assert_called_once_with(context.task.organization, context.task.owner)
    assert context.factory.call_args.args == ()
    assert "organization" not in context.factory.call_args.kwargs
    assert not Path(context.factory.call_args.kwargs["working_directory"]).exists()
    options = context.engine.complete.call_args.kwargs
    assert options["cancelled"] is cancelled and options["permission_mode"] == "default"
    assert context.usage.call_args.kwargs["usage"]["total_tokens"] == 50
    assert context.usage.call_args.kwargs["provider"] == "codex"
    assert context.usage.call_args.kwargs["model"] == "configured-model"


@pytest.mark.parametrize("config", [{}, {"answer_provider": "missing"}, {"answer_model": "legacy-model"}])
@pytest.mark.parametrize("has_providers", [False, True])
def test_legacy_organization_routes_do_not_affect_system_engine(context, config, has_providers):
    context.task.organization.providers.exists.return_value = has_providers
    assert analysis.call_model(context.task, "test", {}, config) == {"claims": []}
    assert context.factory.call_args.args == ()
    assert set(context.factory.call_args.kwargs) == {"working_directory"}
    assert not context.task.organization.providers.mock_calls


def test_vision_passes_native_images_with_frame_citations(context, monkeypatch, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"image")
    monkeypatch.setattr(analysis, "path_for", lambda key: frame)
    analysis.call_model(context.task, "test", {}, {}, frames=[{"id": "f0", "time": 2, "key": "frame.jpg"}])
    assert context.engine.complete.call_args.kwargs["image_paths"] == [str(frame)]
    assert '"id": "f0"' in context.engine.complete.call_args.args[0][1]["content"]


def test_unsupported_vision_never_generates_without_images(context, monkeypatch, tmp_path):
    context.engine.adapter_name = "graphflow"
    monkeypatch.setattr(analysis, "path_for", lambda key: tmp_path / key)
    with pytest.raises(ValueError, match="图片输入"):
        analysis.call_model(context.task, "test", {}, {}, frames=[{"id": "f0", "time": 0, "key": "frame.jpg"}])
    context.engine.complete.assert_not_called()


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
    cancelled = Mock(side_effect=[False, False, True])
    with pytest.raises(InterruptedError):
        analysis.call_model(context.task, "test", {}, {}, cancelled=cancelled)
    context.usage.assert_not_called()


@pytest.mark.parametrize('seconds', [300, 600])
def test_analysis_uses_configured_generation_deadline(context, settings, seconds):
    settings.APPLICATION_GENERATION_TIMEOUT_SECONDS = seconds
    analysis.call_model(context.task, '分析账号', {'works': []}, {})
    assert context.engine.complete.call_args.kwargs['timeout_seconds'] == seconds


def test_analysis_timeout_is_explicit_and_not_retried(context, settings):
    settings.APPLICATION_GENERATION_TIMEOUT_SECONDS = 300
    context.engine.complete.side_effect = TimeoutError('private provider details')
    with pytest.raises(ValueError, match='生成超时') as caught:
        analysis.call_claims(context.task, '分析账号', {'works': []}, {}, {'work-1'})
    assert '300' in str(caught.value)
    assert '登录' not in str(caught.value) and 'private' not in str(caught.value)
    context.engine.complete.assert_called_once()
    context.usage.assert_not_called()
    assert not Path(context.factory.call_args.kwargs['working_directory']).exists()

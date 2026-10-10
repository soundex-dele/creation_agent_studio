import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm import application
from app_center.kitchen_assistant import runtime as kitchen
from app_center.prompt_master import runtime as prompt
from app_center.research_assistant import runtime as research
from app_center.rental_growth_assistant import runtime as rental
from app_center.douyin_benchmark.backend import analysis as douyin


@pytest.mark.parametrize("app", ["kitchen", "prompt", "research", "rental", "douyin"])
@pytest.mark.parametrize("adapter", ["codex", "graphflow"])
@pytest.mark.parametrize("config", [{}, {"answer_provider": "disabled", "answer_model": "old-api-model"}])
def test_application_uses_system_engine_without_accessing_organization_routes(monkeypatch, app, adapter, config):
    # Deliberately no providers relation: generation must not inspect organization routes.
    organization, user = object(), object()
    owner = SimpleNamespace(organization=organization, owner=user, id="project")
    engine = Mock(adapter_name=adapter)
    engine.complete.return_value = LLMResponse(
        content='```json\n{"answer":"测试结果"}\n```', model="system-default",
        usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )
    factory, quota, usage = Mock(return_value=engine), Mock(), Mock()
    monkeypatch.setattr(application, "build_agent_engine", factory)
    monkeypatch.setattr(application, "enforce_member_token_quota", quota)
    monkeypatch.setattr(application, "record_usage", usage)
    if app == "kitchen":
        result = kitchen.call_model(SimpleNamespace(
            state=owner, pk="task", kind="question", instruction="小火怎么判断",
            snapshot={"activeRecipe": {"name": "汤"}, "conversation": []},
        ), config)
        resource_type = "kitchen_generation"
    elif app == "prompt":
        result = prompt.call_model(SimpleNamespace(
            session=owner, pk="task", kind="analyze", snapshot={"topic": "写作"},
        ), config)
        resource_type = "prompt_generation"
    elif app == "research":
        result = research.call_model(owner, "提取证据", {"资料": "原文"}, config)
        resource_type = "research_generation"
    elif app == "rental":
        result = rental.call_model(SimpleNamespace(
            organization=organization, owner=user, pk='task', kind='reply', snapshot={},
        ), cancelled=lambda: False)
        resource_type = "rental_generation"
    else:
        result = douyin.call_model(owner, "提取证据", {"资料": "原文"}, config)
        resource_type = "douyin_analysis"
    assert result == {"answer": "测试结果"}
    quota.assert_called_once_with(organization, user)
    assert factory.call_args.args == ()
    assert set(factory.call_args.kwargs) == {"working_directory"}
    assert not Path(factory.call_args.kwargs["working_directory"]).exists()
    messages = engine.complete.call_args.args[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert isinstance(json.loads(messages[1]["content"]), dict)
    assert engine.complete.call_count == 1
    assert engine.complete.call_args.kwargs["require_tool_approval"] is True
    assert engine.complete.call_args.kwargs.get("final_response_only") is (True if adapter == "codex" else None)
    recorded = usage.call_args.kwargs
    assert recorded["organization"] is organization and recorded["user"] is user
    assert recorded["resource_type"] == resource_type
    assert recorded["provider"] == adapter and recorded["model"] == "system-default"
    assert recorded["usage"]["total_tokens"] == 8


def test_system_factory_does_not_resolve_organization_provider(monkeypatch, settings):
    from core.llm import factory

    settings.AGENT_ENGINE_ADAPTER = "graphflow"
    constructor = Mock()
    route = Mock(side_effect=AssertionError("Organization routing must not be used"))
    monkeypatch.setattr(factory, "AgentEngine", constructor)
    monkeypatch.setattr("apps.enterprise.services.resolve_provider", route)
    factory.build_agent_engine(working_directory="/tmp/app-generation")
    route.assert_not_called()
    assert constructor.call_args.kwargs == {
        "adapter_name": "graphflow", "model": None,
        "working_directory": "/tmp/app-generation",
    }


def test_application_stream_callback_reaches_engine_before_completion(monkeypatch):
    events = []
    def complete(messages, **kwargs):
        callback = kwargs['on_event']
        callback('output.delta', {'text': '{"answer":"实'})
        callback('output.delta', {'text': '时"}'})
        assert len(events) == 2
        return LLMResponse(content='{"answer":"实时"}', model='system-default', usage=TokenUsage(total_tokens=4))
    engine = Mock(adapter_name='codex'); engine.complete.side_effect = complete
    monkeypatch.setattr(application, 'build_agent_engine', Mock(return_value=engine))
    monkeypatch.setattr(application, 'enforce_member_token_quota', Mock())
    usage = Mock(); monkeypatch.setattr(application, 'record_usage', usage)
    result = application.generate_json(organization=object(), user=object(), resource_type='rental_generation',
        resource_id='task', instruction='生成', content='{}', on_event=lambda kind, payload: events.append((kind, payload)))
    assert result == {'answer': '实时'}
    usage.assert_called_once()


@pytest.mark.parametrize('phase', [None, 'final_answer'])
def test_json_generation_uses_replacement_message_not_abandoned_draft(monkeypatch, phase):
    from core.agent_engine.adapters.codex import CodexAdapter, _AppServerSdk
    from core.agent_engine.engine import AgentEngine

    output = {'text': '# 完整标题\n\n完整正文，包含 {花括号} 与代码 `x`。'}
    raw = json.dumps(output, ensure_ascii=False)
    thread = Mock(id='thread-1')
    thread.turn.return_value.stream.return_value = iter([
        {'method': 'item/completed', 'payload': {'item': {
            'id': 'draft', 'type': 'agentMessage', 'text': '{"text":"# 未完成草稿',
        }}},
        {'method': 'item/started', 'payload': {'item': {
            'id': 'answer', 'type': 'agentMessage', 'text': '', 'phase': phase,
        }}},
        {'method': 'item/agentMessage/delta', 'payload': {'itemId': 'answer', 'delta': raw[:12]}},
        {'method': 'item/agentMessage/delta', 'payload': {'itemId': 'answer', 'delta': raw[12:]}},
        {'method': 'item/completed', 'payload': {'item': {
            'id': 'answer', 'type': 'agentMessage', 'text': raw, 'phase': phase,
        }}},
        {'method': 'turn/completed', 'payload': {'turn': {'status': 'completed'}}},
    ])
    client = Mock(input_request=None)
    client.thread_start.return_value = thread
    adapter = CodexAdapter()
    monkeypatch.setattr(adapter, '_client', lambda **kwargs: (_AppServerSdk, client))
    monkeypatch.setattr(application, 'build_agent_engine', lambda **kwargs: AgentEngine(adapter=adapter))
    monkeypatch.setattr(application, 'enforce_member_token_quota', Mock())
    monkeypatch.setattr(application, 'record_usage', Mock())
    events = []
    result = application.generate_json(
        organization=object(), user=object(), resource_type='douyin_analysis', resource_id='task',
        instruction='仅返回 JSON', content='{}', on_event=lambda *event: events.append(event),
    )
    assert result == output
    preview = ''
    for kind, payload in events:
        if kind == 'output.snapshot':
            preview = payload['text']
        elif kind == 'output.delta':
            preview += payload['text']
    assert preview == raw
    thread.turn.assert_called_once()
    client.close.assert_called_once()

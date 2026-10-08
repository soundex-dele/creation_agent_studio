import queue
import threading
from unittest.mock import MagicMock

import pytest

from core.agent_engine.adapters.codex import _AppServerTransport, _AppServerThread, _consume_codex_turn
from core.agent_engine.adapters.codex_interactions import input_request, response_for_request
from modules.execution.application.agent_activity import reduce_activity


def transport():
    value = object.__new__(_AppServerTransport)
    value.live_interactions = True
    value._server_requests = {}
    value._server_request_lock = threading.Lock()
    value._notifications = queue.Queue()
    value._process = MagicMock()
    value._process.poll.return_value = None
    value._send = MagicMock()
    value.request = MagicMock(return_value={"turn": {"id": "turn-1"}})
    return value


def request(method="item/commandExecution/requestApproval", **params):
    return {"id": 47, "method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", **params}}


def test_answers_original_rpc_without_new_turn_or_replaying_authorization():
    server = transport()
    message = request(command="pwd")
    server._handle_server_request(message)

    def answer(prompt, *, is_pending):
        assert prompt["codex_request"]["id"] == 47
        assert is_pending()
        server._send.assert_not_called()
        server._notifications.put({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
        return {"type": "grant_permission", "payload": {"selections": ["accept"]}}

    result = _consume_codex_turn(_AppServerThread(transport=server, thread_id="thread-1"), "hi", on_input_request=answer)
    assert result.status == "completed"
    server._send.assert_called_once_with({"id": 47, "result": {"decision": "accept"}})
    assert server.request.call_count == 1
    assert server.request.call_args.args[0] == "turn/start"
    assert not server.respond(message, {"decision": "accept"})
    assert not server.is_pending(message)


def test_stale_and_changed_requests_cannot_be_answered():
    server = transport()
    first = request(command="pwd")
    server._handle_server_request(first)
    changed = request(command="rm -rf important")
    assert not server.respond(changed, {"decision": "accept"})
    server._server_requests.clear()  # serverRequest/resolved
    assert not server.respond(first, {"decision": "accept"})
    server._send.assert_not_called()


def test_permissions_cannot_be_expanded_by_client_and_denial_never_grants():
    message = request("item/permissions/requestApproval", permissions={"network": {"enabled": True}})
    result = response_for_request(message, {"type": "grant_permission", "payload": {
        "selections": ["acceptForSession"], "permissions": {"fileSystem": {"write": ["/"]}},
    }})
    assert result == {"permissions": {"network": {"enabled": True}}, "scope": "session"}
    assert response_for_request(message, {"type": "deny_permission", "payload": {"selections": ["accept"]}})["permissions"] == {}


def test_approval_only_accepts_offered_decisions():
    message = request(availableDecisions=["accept", "decline"])
    with pytest.raises(ValueError):
        response_for_request(message, {"type": "grant_permission", "payload": {"selections": ["acceptForSession"]}})


def test_question_answers_keep_question_ids_and_validate_missing_answers():
    message = request("item/tool/requestUserInput", questions=[{"id": "framework", "question": "框架", "header": "框架", "options": []}])
    result = response_for_request(message, {"type": "answer", "payload": {"answers": {"framework": {"answers": ["React"]}}}})
    assert result == {"answers": {"framework": {"answers": ["React"]}}}
    with pytest.raises(ValueError):
        response_for_request(message, {"type": "answer", "payload": {"answers": {}}})


def test_mcp_form_uses_typed_content_and_validates_schema():
    message = request("mcpServer/elicitation/request", mode="form", requestedSchema={
        "type": "object", "properties": {"count": {"type": "integer", "minimum": 1}}, "required": ["count"],
    })
    assert input_request(message)["elicitation"] is True
    with pytest.raises(ValueError):
        response_for_request(message, {"payload": {"content": {"count": "one"}}})
    assert response_for_request(message, {"payload": {"content": {"count": 2}}})["content"] == {"count": 2}
    assert response_for_request(message, {"payload": {"action": "decline"}})["content"] is None


def test_dynamic_tools_return_a_protocol_result():
    server = transport()
    server._handle_server_request(request("item/tool/call", tool="lookup", arguments={"key": "name"}))
    server._notifications.put({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
    _consume_codex_turn(_AppServerThread(transport=server, thread_id="thread-1"), "hi",
                        tool_handlers={"lookup": lambda args: args["key"]})
    server._send.assert_called_once_with({"id": 47, "result": {"success": True, "contentItems": [{"type": "inputText", "text": "name"}]}})


def test_activity_excludes_raw_reasoning_and_keeps_steps_logs_diff_errors():
    server = transport()
    for method, payload in [
        ("item/completed", {"item": {"id": "r", "type": "reasoning", "summary": ["Checking"], "content": ["private"]}}),
        ("turn/plan/updated", {"plan": [{"step": "Test", "status": "inProgress"}]}),
        ("item/commandExecution/outputDelta", {"itemId": "tool", "delta": "log\n"}),
        ("turn/diff/updated", {"diff": "+changed"}),
        ("warning", {"message": "check config"}),
        ("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}}),
    ]:
        server._notifications.put({"method": method, "params": payload})
    events = []
    _consume_codex_turn(_AppServerThread(transport=server, thread_id="thread-1"), "hi", on_event=lambda *args: events.append(args))
    state = {}
    for kind, payload in events:
        state = reduce_activity(state, kind, payload)
    assert "content" not in state["items"]["r"]
    assert state["items"]["r"]["summary"] == ["Checking"]
    assert state["plan"]["plan"][0]["status"] == "inProgress"
    assert state["tools"]["tool"]["output"] == "log\n"
    assert state["diff"]["diff"] == "+changed"
    assert state["warnings"][0]["message"] == "check config"


def test_steer_reuses_active_turn():
    server = transport()
    server._notifications.put({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
    _consume_codex_turn(_AppServerThread(transport=server, thread_id="thread-1"), "hi",
                        poll_commands=lambda: [{"type": "steer", "payload": {"text": "focus tests"}}])
    assert server.request.call_args.args[0] == "turn/steer"
    assert server.request.call_args.args[1]["expectedTurnId"] == "turn-1"


@pytest.mark.parametrize('method,payload', [
    ('item/commandExecution/requestApproval', {'selections': {}}),
    ('item/commandExecution/requestApproval', {'selections': [{}]}),
    ('item/commandExecution/requestApproval', {'selections': ['0']}),
    ('mcpServer/elicitation/request', {'action': {}}),
    ('item/tool/requestUserInput', {'answers': {'framework': []}}),
])
def test_malformed_interaction_payloads_are_rejected(method, payload):
    with pytest.raises(ValueError):
        response_for_request(request(method, questions=[{'id': 'framework'}]), {'payload': payload})


def test_rule_approval_returns_only_original_server_rule():
    rule = {'acceptWithExecpolicyAmendment': {'execpolicy_amendment': ['git', 'status']}}
    message = request(availableDecisions=['accept', rule, 'decline'])
    assert response_for_request(message, {'payload': {'selections': ['rule:1']}}) == {'decision': rule}


def test_activity_snapshot_preserves_structured_values():
    from types import SimpleNamespace
    from modules.execution.application.event_retention import empty_projection, apply_projection_event
    projection = empty_projection('run-1')
    for index, (kind, payload) in enumerate([
        ('agent.session', {'can_steer': True}),
        ('agent.item', {'id': 'plan', 'type': 'plan', 'text': '# Plan'}),
        ('agent.tool', {'id': 'shell', 'delta': 'one'}),
        ('agent.tool', {'id': 'shell', 'delta': 'two'}),
    ], 1):
        projection = apply_projection_event(projection, SimpleNamespace(run_id='run-1', type=kind, payload=payload, sequence=index))
    assert projection['activity']['items']['plan']['text'] == '# Plan'
    assert projection['activity']['tools']['shell']['output'] == 'onetwo'
    projection = apply_projection_event(projection, SimpleNamespace(run_id='run-1', type='input.resolved', payload={}, sequence=5))
    assert projection['activity'] == {'session': {'can_steer': True}}
    assert projection['status'] == 'running'


@pytest.mark.parametrize('interrupt_fails', [False, True])
def test_expired_turn_is_interrupted_and_preserves_timeout(monkeypatch, caplog, interrupt_fails):
    from core.agent_engine.adapters import codex
    now = [0.0]
    monkeypatch.setattr(codex.time, 'monotonic', lambda: now[0])
    server = transport()

    def rpc(method, params):
        if method == 'turn/interrupt' and interrupt_fails:
            raise RuntimeError('private upstream details')
        return {'turn': {'id': 'turn-1'}}

    def wait_for_notification(timeout=None):
        now[0] = 301.0
        raise queue.Empty

    server.request.side_effect = rpc
    server.next_notification = MagicMock(side_effect=wait_for_notification)
    with pytest.raises(TimeoutError, match='生成超时') as caught:
        _consume_codex_turn(_AppServerThread(transport=server, thread_id='thread-1'),
            'private prompt', timeout_seconds=300)
    assert '图像' not in str(caught.value)
    assert [call.args[0] for call in server.request.call_args_list] == ['turn/start', 'turn/interrupt']
    assert server.request.call_args.args[1] == {'threadId': 'thread-1', 'turnId': 'turn-1'}
    assert 'private' not in caplog.text


def test_turn_can_finish_after_old_120_second_limit(monkeypatch):
    from core.agent_engine.adapters import codex
    now = [0.0]
    monkeypatch.setattr(codex.time, 'monotonic', lambda: now[0])
    server = transport()
    notifications = iter([
        {'method': 'item/completed', 'params': {'item': {
            'id': 'answer', 'type': 'agentMessage', 'text': '{"claims": []}'}}},
        {'method': 'turn/completed', 'params': {'turn': {'id': 'turn-1', 'status': 'completed'}}},
    ])

    def wait_for_notification(timeout=None):
        now[0] = 180.0
        return next(notifications)

    server.next_notification = MagicMock(side_effect=wait_for_notification)
    result = _consume_codex_turn(_AppServerThread(transport=server, thread_id='thread-1'),
        'analyze', timeout_seconds=300)
    assert result.status == 'completed'
    assert result.final_response == '{"claims": []}'
    assert server.request.call_count == 1

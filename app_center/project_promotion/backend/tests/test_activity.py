import json
import pytest
from ..activity import ActivityLog, MAX_ITEMS, display_text


def tool(**kwargs):
    return dict(tool_call_id='one', name='read', tool_type='commandExecution', input='cat app.py', **kwargs)


def test_tool_history_merges_status_and_retains_input_without_raw_output():
    log = ActivityLog()
    log.record('session.started', {})
    log.record('tool.started', tool())
    log.record('tool.completed', {**tool(), 'input': None, 'result': 'private source', 'error_message': 'private error'})
    assert len(log.items) == 2
    assert log.items[-1]['status'] == 'completed'
    assert log.items[-1]['detail'] == 'cat app.py'
    assert 'private' not in json.dumps(log.snapshot())
    assert log.record('tool.completed', tool()) is None
    log.record('agent.item', {'type': 'reasoning', 'completed': True, 'summary': ['private reasoning'], 'text': 'secret'})
    log.record('agent.tool', {'delta': 'raw command output'})
    assert len(log.items) == 2


def test_retry_is_separate_session_and_unfinished_commands_do_not_look_complete():
    log = ActivityLog()
    log.record('session.started', {})
    log.record('tool.started', tool())
    log.record('session.started', {})
    log.record('tool.failed', tool())
    assert [row['status'] for row in log.items] == ['completed', 'stopped', 'completed', 'failed']
    assert log.items[1]['id'] != log.items[3]['id']


def test_comments_plans_citations_and_bounded_redacted_details():
    log = ActivityLog()
    log.record('agent.item', {'type': 'agentMessage', 'completed': True, 'id': 'msg', 'text': '检查入口文件'})
    log.record('agent.plan', {'plan': [{'step': '查找实现'}]})
    log.record('tool.started', {'name': 'promotion_cite_sources', 'input': {'sources': [{'path': 'app.py', 'start': 1, 'end': 2}]}})
    assert [row['detail'] for row in log.items] == ['检查入口文件', '查找实现', 'app.py:1-2']
    log.record('tool.failed', {'name': 'promotion_cite_sources', 'input': {'sources': None}})
    assert 'sensitive' not in display_text('API_KEY=sensitive Bearer sensitive password="sensitive"')
    assert '已截断' in display_text('a' * 5000)
    for _ in range(MAX_ITEMS + 1):
        log.record('stage', {'text': '读取中'})
    assert len(log.items) == MAX_ITEMS and log.dropped == 5

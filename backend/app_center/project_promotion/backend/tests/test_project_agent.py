import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm.application import GenerationError
from .. import project_agent, project_source
from .test_project_source import model_result


@pytest.fixture
def context(monkeypatch, settings):
    settings.CODEX_TRANSPORT = 'app-server'
    settings.PROJECT_PROMOTION_ALLOW_FULL_DISK_READ = False
    task = SimpleNamespace(pk='task', owner=object(), organization=object(), snapshot={'request': {
        'project_path': '/project', 'instruction': '找到可演示的功能'}})
    files = {'app.py': {'text': '\n'.join(f'line{i}' for i in range(1, 201)), 'sha256': 'a' * 64},
             'README.md': {'text': 'documentation', 'sha256': 'b' * 64}}
    monkeypatch.setattr(project_source, 'which', lambda _: 'git')
    monkeypatch.setattr(project_source, 'from_local', lambda *args: (files, {}, {'path': '/project'}))
    engine = Mock(adapter_name='codex')
    factory = Mock(return_value=engine)
    monkeypatch.setattr(project_agent, 'build_agent_engine', factory)
    monkeypatch.setattr(project_agent, 'enforce_member_token_quota', Mock())
    usage = Mock(); monkeypatch.setattr(project_agent, 'record_usage', usage)
    stages = []
    return SimpleNamespace(task=task, files=files, engine=engine, factory=factory, usage=usage, stages=stages)


def execute(context, check=lambda: None):
    return project_source.explore_project(context.task, lambda **kwargs: project_agent.run_project_agent(
        context.task, **kwargs, progress=context.stages.append, check=check), context.stages.append, check)


def response(**kwargs):
    return LLMResponse(content='已完成', model='configured', usage=TokenUsage(total_tokens=10), thread_id='native-thread', **kwargs)


@pytest.mark.parametrize('full_disk', [False, True])
def test_one_native_session_reads_batch_and_submits_instead_of_stateless_rounds(context, settings, full_disk):
    settings.PROJECT_PROMOTION_ALLOW_FULL_DISK_READ = full_disk
    def complete(messages, **options):
        assert len(messages) == 2 and 'line100' not in messages[1]['content']
        path = Path(options['working_directory']) if 'working_directory' in options else Path(context.factory.call_args.kwargs['working_directory'])
        assert (path / 'app.py').read_text(encoding='utf8').count('\n') == 199
        assert options['read_only_paths'] == [str(path)]
        assert options['permission_mode'] == 'default'
        assert options['read_only_full_disk'] is full_disk
        options['on_event']('tool.started', {'command': 'private command not for progress'})
        tools = options['tool_handlers']
        evidence = json.loads(tools['promotion_cite_sources']({'sources': [
            {'path': 'app.py', 'start': 1, 'end': 200}, {'path': 'README.md', 'start': 1, 'end': 1}]}))['evidence']
        assert len(evidence) == 2 and 'line200' in evidence[0]['quote']
        tools['promotion_submit_cases'](model_result([row['id'] for row in evidence]))
        return response()
    context.engine.complete.side_effect = complete
    result = execute(context)
    context.engine.complete.assert_called_once()
    assert len(result['cases']) == 2
    assert context.task.snapshot['project_source']['thread_id'] == 'native-thread'
    assert not Path(context.factory.call_args.kwargs['working_directory']).exists()
    assert all('private command' not in stage and '第1轮' not in stage for stage in context.stages)
    assert context.usage.call_args.kwargs['status'] == 'success'


@pytest.mark.parametrize('path,start,end', [('../outside.py', 1, 1), ('/app.py', 1, 1),
    ('C:/secret.py', 1, 1), ('app.py', 0, 1), ('app.py', 201, 202), ('app.py', 2, 1)])
def test_citations_enforce_snapshot_paths_and_line_ranges(context, path, start, end):
    tools = project_source.ProjectTools(context.files, {}, lambda _: None, lambda: None)
    with pytest.raises((ValueError, project_source.ValidationError)):
        tools.cite({'sources': [{'path': path, 'start': start, 'end': end}]})
    assert tools.evidence == {}


def test_source_tool_uses_server_content_and_deduplicates(context):
    tools = project_source.ProjectTools(context.files, {}, lambda _: None, lambda: None)
    args = {'sources': [{'path': 'app.py', 'start': 81, 'end': 200}]}
    first = json.loads(tools.cite(args))
    assert json.loads(tools.cite(args)) == first
    assert first['evidence'][0]['sha256'] == 'a' * 64
    assert len(tools.evidence) == 1
    with pytest.raises(project_source.ValidationError):
        tools.cite({'sources': [{**args['sources'][0], 'quote': 'forged'}]})


def test_no_submitted_result_is_not_success(context):
    context.engine.complete.return_value = response()
    with pytest.raises(GenerationError, match='未提交有效案例'):
        execute(context)
    context.engine.complete.assert_called_once()


def test_insufficient_evidence_finishes_one_session_without_inventing_cases(context):
    def complete(messages, **options):
        result = json.loads(options['tool_handlers']['promotion_submit_cases'](
            {'insufficient_reason': '仅有说明，缺少可展示的功能证据'}))
        assert result['accepted'] and result['case_count'] == 0
        return response()
    context.engine.complete.side_effect = complete
    with pytest.raises(GenerationError) as caught:
        execute(context)
    assert caught.value.code == 'insufficient_sources'
    context.engine.complete.assert_called_once()
    assert 'project_source' not in context.task.snapshot


def test_failed_agent_never_accepts_partial_submission(context):
    def complete(messages, **options):
        tools = options['tool_handlers']
        evidence = json.loads(tools['promotion_cite_sources']({'sources': [{'path': 'app.py', 'start': 1, 'end': 2}]}))['evidence']
        tools['promotion_submit_cases'](model_result([row['id'] for row in evidence]))
        return response(success=False, error='Selected model is at capacity')
    context.engine.complete.side_effect = complete
    with pytest.raises(GenerationError) as caught:
        execute(context)
    assert caught.value.code == 'engine_overloaded'
    assert 'project_source' not in context.task.snapshot
    assert context.usage.call_args.kwargs['status'] == 'error'


def test_unsupported_adapter_never_falls_back_to_stateless_exploration(context):
    context.engine.adapter_name = 'graphflow'
    with pytest.raises(GenerationError) as caught:
        execute(context)
    assert caught.value.code == 'unsupported_agent'
    context.engine.complete.assert_not_called()


@pytest.mark.parametrize('error,code', [
    ('elevated Windows sandbox requires effective `:root` read access', 'sandbox_read_scope_unsupported'),
    ('failed to prepare fs sandbox: CryptUnprotectData failed: 2148073483', 'sandbox_unavailable'),
    ('Codex app-server did not activate the restricted read-only permissions profile', 'unsupported_agent'),
])
def test_native_setup_errors_are_actionable_and_preserve_existing_content(context, error, code):
    context.engine.complete.side_effect = RuntimeError(error)
    with pytest.raises(GenerationError) as caught:
        execute(context)
    assert caught.value.code == code
    assert 'project_source' not in context.task.snapshot
    assert not Path(context.factory.call_args.kwargs['working_directory']).exists()


def test_cancellation_stops_agent_and_cleans_snapshot(context):
    stopped = False
    def check():
        if stopped:
            raise InterruptedError()
    def complete(messages, **options):
        nonlocal stopped
        stopped = True
        assert options['cancelled']()
        return response()
    context.engine.complete.side_effect = complete
    with pytest.raises(InterruptedError):
        execute(context, check)
    assert not Path(context.factory.call_args.kwargs['working_directory']).exists()
    assert 'project_source' not in context.task.snapshot


def test_agent_forwards_activity_events_without_restarting_session(context):
    events = []
    def complete(messages, **options):
        options['on_event']('tool.started', {'tool_call_id': 'read1', 'name': 'read'})
        options['on_event']('tool.completed', {'tool_call_id': 'read1', 'name': 'read'})
        return response()
    context.engine.complete.side_effect = complete
    project_agent.run_project_agent(context.task, working_directory='/snapshot', instruction='test', content={},
        tools=[], handlers={}, progress=context.stages.append, check=lambda: None,
        on_activity=lambda kind, payload: events.append((kind, payload)))
    assert [kind for kind, payload in events] == ['session.started', 'tool.started', 'tool.completed']
    context.engine.complete.assert_called_once()

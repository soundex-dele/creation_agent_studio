import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm.application import GenerationError
from .. import project_agent, project_source
from ..catalog import EXPLORATION_FOCUSES, MATERIAL_CATALOG
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
        assert set(tools) == {'promotion_submit_cases'}
        tools['promotion_submit_cases'](model_result())
        return response()
    context.engine.complete.side_effect = complete
    result = execute(context)
    context.engine.complete.assert_called_once()
    assert len(result['cases']) == 2
    assert context.task.snapshot['project_source']['thread_id'] == 'native-thread'
    assert not Path(context.factory.call_args.kwargs['working_directory']).exists()
    assert all('private command' not in stage and '第1轮' not in stage for stage in context.stages)
    assert context.usage.call_args.kwargs['status'] == 'success'


def test_submission_tool_requires_no_source_registration_and_checks_cancellation(context):
    check = Mock()
    tools = project_source.ProjectTools({}, lambda _: None, check)
    assert [tool['name'] for tool in tools.definitions()] == ['promotion_submit_cases']
    assert json.loads(tools.submit(model_result()))['accepted'] is True
    check.assert_called_once()
    check.side_effect = InterruptedError()
    with pytest.raises(InterruptedError):
        tools.submit(model_result())


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
        tools['promotion_submit_cases'](model_result())
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


@pytest.mark.parametrize('mode,expected', [('overview', 610), ('deep', 1210)])
def test_exploration_modes_use_distinct_scope_and_deadlines(context, settings, mode, expected):
    settings.APPLICATION_GENERATION_TIMEOUT_SECONDS = 5
    settings.PROJECT_PROMOTION_OVERVIEW_TIMEOUT_SECONDS = 610
    settings.PROJECT_PROMOTION_DEEP_TIMEOUT_SECONDS = 1210
    context.task.snapshot['request']['exploration_mode'] = mode
    context.task.snapshot['request']['instruction'] = '任务调度'
    def complete(messages, **options):
        assert options['timeout_seconds'] == expected
        system = messages[0]['content']
        if mode == 'overview':
            assert '主要模块都已归纳或明确标注资料缺口' in system
            assert '不要逐项展开调用链' in system
            assert project_source.DEEP_INSTRUCTION not in system
        else:
            assert '不要再次遍历所有无关模块' in system
            assert project_source.OVERVIEW_INSTRUCTION not in system
        tools = options['tool_handlers']
        tools['promotion_submit_cases'](model_result())
        return response()
    context.engine.complete.side_effect = complete
    result = execute(context)
    assert result['cases'][0]['source_snapshot']['exploration_mode'] == mode


def test_legacy_project_requests_default_to_whole_project_overview(context):
    def complete(messages, **options):
        assert project_source.OVERVIEW_INSTRUCTION in messages[0]['content']
        assert json.loads(messages[1]['content'])['探索模式'] == 'overview'
        options['tool_handlers']['promotion_submit_cases']({'insufficient_reason': '测试资料不足'})
        return response()
    context.engine.complete.side_effect = complete
    with pytest.raises(GenerationError) as error:
        execute(context)
    assert error.value.code == 'insufficient_sources'


@pytest.mark.parametrize('mode,label,limit', [('overview', '全面概览', 600), ('deep', '指定方向深挖', 1200)])
def test_timeout_explains_mode_limit_and_cleans_snapshot(context, settings, mode, label, limit):
    settings.PROJECT_PROMOTION_OVERVIEW_TIMEOUT_SECONDS = 600
    settings.PROJECT_PROMOTION_DEEP_TIMEOUT_SECONDS = 1200
    context.task.snapshot['request']['exploration_mode'] = mode
    context.engine.complete.side_effect = TimeoutError('private provider detail')
    with pytest.raises(GenerationError) as error:
        execute(context)
    assert error.value.code == 'timeout'
    assert label in str(error.value) and f'{limit} 秒' in str(error.value)
    assert 'private' not in str(error.value) and '缩小探索方向' not in str(error.value)
    assert not Path(context.factory.call_args.kwargs['working_directory']).exists()
    assert 'project_source' not in context.task.snapshot


@pytest.mark.parametrize('focus', EXPLORATION_FOCUSES)
@pytest.mark.parametrize('mode', ['overview', 'deep'])
def test_selected_focus_reaches_agent_without_changing_exploration_scope(context, focus, mode):
    context.task.snapshot['request'].update(exploration_focus=focus, exploration_mode=mode)
    def complete(messages, **options):
        instruction = messages[0]['content']
        label, description = EXPLORATION_FOCUSES[focus]
        if mode == 'overview':
            assert f'本次探索侧重：{label}' in instruction and description in instruction
            assert json.loads(messages[1]['content'])['素材分类'] == project_source.allowed_material_types(focus)
        else:
            assert '本次探索侧重' not in instruction
            assert '素材分类' not in json.loads(messages[1]['content'])
        assert (project_source.OVERVIEW_INSTRUCTION if mode == 'overview' else project_source.DEEP_INSTRUCTION) in instruction
        if mode == 'overview' and focus in MATERIAL_CATALOG:
            assert f'仅输出 material_type={focus}' in instruction
            assert '不要附带其他分类' in instruction
        value = model_result()
        if focus == 'overview':
            value['cases'] = value['cases'][:1]
        for item in value['cases']:
            item['data'].update(material_type=focus if focus in MATERIAL_CATALOG else 'feature', summary='摘要', facts='项目资料')
        options['tool_handlers']['promotion_submit_cases'](value)
        return response()
    context.engine.complete.side_effect = complete
    result = execute(context)
    assert result['cases'][0]['source_snapshot'].get('exploration_focus') == (focus if mode == 'overview' else None)
    assert result['cases'][0]['data']['evidence'] == ''


def test_deep_agent_ignores_categories_in_old_source_snapshot(context):
    context.task.snapshot['request'].update(exploration_mode='deep', material_types=['deployment'], exploration_focus='security')
    def complete(messages, **options):
        assert '不受概览时所选分类限制' in messages[0]['content']
        assert '素材分类' not in json.loads(messages[1]['content'])
        value = model_result()
        for item in value['cases']:
            item['data']['material_type'] = 'workflow'
        options['tool_handlers']['promotion_submit_cases'](value)
        return response()
    context.engine.complete.side_effect = complete
    result = execute(context)
    source = result['cases'][0]['source_snapshot']
    assert 'material_types' not in source and 'exploration_focus' not in source
    assert source['exploration_mode'] == 'deep'

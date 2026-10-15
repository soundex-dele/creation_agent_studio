import json
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
from rest_framework.exceptions import ValidationError
from core.llm.application import GenerationError
from core.user_directories import user_directory
from app_center.project_promotion import runtime
from .. import project_source
from ..catalog import MATERIAL_CATALOG, BROAD_FOCUSES
from ..models import AITask, Case
from .test_promotion import ctx, post, get, patch, case, Sink


@pytest.fixture
def repo(ctx, tmp_path, settings):
    settings.AGENT_WORKSPACE_ROOT = tmp_path / 'workspaces'
    path = user_directory(ctx['user']) / 'project'
    path.mkdir()
    (path / 'README.md').write_text('Article formatting project. Future: batch export.', encoding='utf8')
    (path / 'app.py').write_text('def render(article):\n    return "<p>" + article + "</p>"\n', encoding='utf8')
    (path / '.gitignore').write_text('ignored.txt\n', encoding='utf8')
    for args in [('init',), ('add', '.'), ('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'initial')]:
        subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)
    (path / 'app.py').write_text('def render(article):\n    return "<article>" + article + "</article>"\n', encoding='utf8')
    (path / 'notes.md').write_text('Uncommitted working tree note', encoding='utf8')
    (path / '.env').write_text('SECRET=excluded-marker', encoding='utf8')
    (path / 'ignored.txt').write_text('ignored-marker', encoding='utf8')
    return path


def submit(ctx, repo, key='project'):
    return post(ctx, 'ai/tasks', dict(kind='project', project_path=str(repo), request_key=key), 202)


def run(ctx, task, sink=None):
    return runtime.execute(dict(run_id=task['run_id'], organization_id=str(ctx['org'].pk), input={'task_id': task['id']}), sink or Sink())


def model_result():
    return dict(analysis='Source-backed drafts; static reading only.', cases=[dict(title=title,
        data=dict(audience='创作者', problem='排版耗时', solution='格式化文章', implemented='输出 article 标签',
                  case_type='customer', assets=[dict(label='Invented', url='https://example.com/fake')]))
        for title in ['文章排版演示', '格式化实现记录']])


def project_model(monkeypatch):
    calls = []
    def generate(task, **kwargs):
        calls.append(kwargs)
        path = Path(kwargs['working_directory'])
        assert not (path / '.env').exists() and not (path / 'ignored.txt').exists()
        assert 'Uncommitted working tree note' in (path / 'notes.md').read_text(encoding='utf8')
        assert '<article>' in (path / 'app.py').read_text(encoding='utf8')
        assert '当前源码窗口' not in kwargs['content']
        assert set(kwargs['handlers']) == {'promotion_submit_cases'}
        invalid = model_result()
        invalid['cases'][0]['data']['material_type'] = 'invalid'
        with pytest.raises(ValidationError):
            kwargs['handlers']['promotion_submit_cases'](invalid)
        kwargs['handlers']['promotion_submit_cases'](model_result())
        return 'native-thread-1'
    monkeypatch.setattr(runtime, 'run_project_agent', generate)
    monkeypatch.setattr(runtime, 'generate_json', lambda **kwargs: pytest.fail('Project used stateless JSON generation'))
    return calls


def test_project_exploration_batch_apply_and_immutable_evidence(ctx, repo, monkeypatch):
    calls = project_model(monkeypatch)
    task = submit(ctx, repo)
    assert post(ctx, 'ai/tasks', dict(kind='project', project_path=str(repo), request_key='project'), 200)['id'] == task['id']
    run(ctx, task)
    task = get(ctx, f"ai/tasks/{task['id']}")
    assert task['status'] == 'succeeded' and task['stage']
    assert Case.objects.count() == 0
    assert len(calls) == 1
    assert not Path(calls[0]['working_directory']).exists()
    original = task['result']['cases'][0]['source_snapshot']
    assert not {'evidence', 'coverage', 'digest'} & original.keys()
    assert original['origin']['working_tree'] is True
    assert task['result']['cases'][0]['data']['evidence'] == ''
    (repo / 'app.py').write_text('changed after exploration', encoding='utf8')
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    assert Case.objects.count() == 2
    row = get(ctx, 'cases/' + applied['result']['case_ids'][0])
    assert row['status'] == 'draft' and row['data']['case_type'] == 'demo' and row['data']['assets'] == []
    assert '未运行' in row['data']['conditions']
    assert row['data']['evidence'] == ''
    row = patch(ctx, 'cases', row, {'title': '人工审核标题'})
    assert row['source_snapshot'] == original
    patch(ctx, 'cases', row, {'source_snapshot': {}}, 400)
    ctx['client'].force_authenticate(ctx['other'])
    assert get(ctx, 'cases')['results'] == []
    for suffix in ['', '/apply', '/cancel']:
        url = f"{ctx['root']}/ai/tasks/{task['id']}{suffix}"
        response = ctx['client'].post(url, {}, format='json') if suffix else ctx['client'].get(url)
        assert response.status_code == 404


def test_project_path_validation_and_payload_conflicts(ctx, repo, tmp_path):
    for path in ['', 'relative/path', str(repo / 'missing'), str(tmp_path)]:
        post(ctx, 'ai/tasks', dict(kind='project', project_path=path, request_key='invalid'), 400)
    assert AITask.objects.count() == 0
    task = submit(ctx, repo)
    post(ctx, 'ai/tasks', dict(kind='project', project_path=str(repo), instruction='changed', request_key='project'), 409)
    post(ctx, 'ai/tasks', dict(kind='case', instruction='notes', project_path=str(repo), request_key='wrong-kind'), 400)
    assert AITask.objects.count() == 1 and task['kind'] == 'project'


def test_deep_exploration_requires_a_direction_and_preserves_request_keys(ctx, repo):
    payload = dict(kind='project', project_path=str(repo), exploration_mode='deep', request_key='mode')
    post(ctx, 'ai/tasks', payload, 400)
    post(ctx, 'ai/tasks', {**payload, 'instruction': '   '}, 400)
    payload['instruction'] = '展开文章排版模块'
    task = post(ctx, 'ai/tasks', payload, 202)
    assert task['request']['exploration_mode'] == 'deep'
    assert post(ctx, 'ai/tasks', payload, 200)['id'] == task['id']
    post(ctx, 'ai/tasks', {**payload, 'exploration_mode': 'overview'}, 409)


def test_direct_submission_needs_no_citations_and_discards_generated_evidence():
    value = model_result()
    value['cases'][0]['data']['evidence'] = 'app.py:1-2'
    source = {'origin': {'path': '/project'}}
    result = project_source.validate_project_result(value, source)
    assert result['cases'][0]['data']['implemented']
    assert result['cases'][0]['data']['evidence'] == ''
    assert result['cases'][0]['source_snapshot'] == source
    result['cases'][0]['source_snapshot']['origin']['path'] = 'changed'
    assert source['origin']['path'] == '/project'


def test_duplicates_invalid_fields_and_insufficient_sources_are_rejected():
    value = model_result()
    value['cases'][0]['evidence_ids'] = ['e1']
    with pytest.raises(ValidationError):
        project_source.validate_project_result(value, {})
    value = model_result(); value['cases'][1]['title'] = value['cases'][0]['title']
    with pytest.raises(ValidationError):
        project_source.validate_project_result(value, {})
    with pytest.raises(ValueError, match='资料不足'):
        project_source.validate_project_result({'insufficient_reason': 'No project information'}, {})


def test_failed_generation_preserves_cases_and_can_retry(ctx, repo, monkeypatch):
    existing = case(ctx)
    calls = []
    def generate(task, **kwargs):
        calls.append(kwargs)
        value = model_result()
        value['cases'][0]['data']['material_type'] = 'invalid'
        kwargs['handlers']['promotion_submit_cases'](value)
    monkeypatch.setattr(runtime, 'run_project_agent', generate)
    task = submit(ctx, repo)
    with pytest.raises(RuntimeError):
        run(ctx, task)
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'failed'
    assert len(calls) == 1
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 404)
    assert get(ctx, 'cases')['results'][0]['id'] == existing['id']
    project_model(monkeypatch)
    retried = submit(ctx, repo, 'retry'); run(ctx, retried)
    assert get(ctx, f"ai/tasks/{retried['id']}")['status'] == 'succeeded'


def test_cancel_queued_project(ctx, repo, monkeypatch):
    queued = submit(ctx, repo)
    cancelled = post(ctx, f"ai/tasks/{queued['id']}/cancel", {}, 200)
    assert cancelled['status'] == 'cancelled'
    post(ctx, f"ai/tasks/{queued['id']}/cancel", {}, 200)
    monkeypatch.setattr(project_source, 'from_local', lambda *args: pytest.fail('Cancelled task read files'))
    run(ctx, queued)


def test_cancellation_during_model_call_discards_result(ctx, repo, monkeypatch):
    project_model(monkeypatch)
    task = submit(ctx, repo)
    sink = Sink()
    def cancel(task, **kwargs):
        sink.cancelled = True
        return 'cancelled-thread'
    monkeypatch.setattr(runtime, 'run_project_agent', cancel)
    run(ctx, task, sink)
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'cancelled'
    assert Case.objects.count() == 0
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 404)


def test_revoked_access_prevents_reading_project(ctx, repo, monkeypatch):
    task = submit(ctx, repo)
    ctx['app'].is_active = False; ctx['app'].save()
    monkeypatch.setattr(project_source, 'from_local', lambda *args: pytest.fail('Revoked user read files'))
    with pytest.raises(RuntimeError):
        run(ctx, task)
    assert AITask.objects.get(pk=task['id']).status == 'failed'


def test_empty_or_non_git_project_fails_without_drafts(ctx, repo, monkeypatch):
    empty = repo.parent / 'empty'; empty.mkdir()
    task = submit(ctx, empty)
    monkeypatch.setattr(runtime, 'run_project_agent', lambda *args, **kwargs: pytest.fail('Non-Git project reached model'))
    with pytest.raises(RuntimeError, match='Git'):
        run(ctx, task)
    assert Case.objects.count() == 0


def test_missing_git_has_actionable_error(ctx, repo, monkeypatch):
    task = submit(ctx, repo)
    monkeypatch.setattr(project_source, 'which', lambda _: None)
    with pytest.raises(RuntimeError, match='PATH'):
        run(ctx, task)
    assert 'PATH' in get(ctx, f"ai/tasks/{task['id']}")['error']


def test_cancel_api_during_exploration_prevents_apply(ctx, repo, monkeypatch):
    existing = case(ctx)
    task = submit(ctx, repo)
    def generate(_task, **kwargs):
        post(ctx, f"ai/tasks/{task['id']}/cancel", {}, 200)
        return 'cancelled-thread'
    monkeypatch.setattr(runtime, 'run_project_agent', generate)
    run(ctx, task)
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'cancelled'
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 404)
    assert get(ctx, 'cases')['results'][0]['id'] == existing['id']


@pytest.mark.parametrize('outcome', ['succeeded', 'failed', 'cancelled'])
def test_activity_is_live_private_and_survives_terminal_states(ctx, repo, monkeypatch, outcome):
    task = submit(ctx, repo)
    def generate(_task, **kwargs):
        events = kwargs['on_activity']
        events('session.started', {})
        event = {'tool_call_id': 'read1', 'name': 'read', 'tool_type': 'commandExecution', 'input': 'cat app.py'}
        events('tool.started', event)
        live = get(ctx, f"ai/tasks/{task['id']}")
        assert live['activity']['items'][-1]['status'] == 'running'
        assert live['activity']['items'][-1]['detail'] == 'cat app.py'
        if outcome == 'cancelled':
            post(ctx, f"ai/tasks/{task['id']}/cancel", {}, 200)
            raise InterruptedError()
        events('tool.failed' if outcome == 'failed' else 'tool.completed', {**event, 'result': 'DO NOT STORE RAW OUTPUT'})
        if outcome == 'failed':
            raise GenerationError('模型失败')
        kwargs['handlers']['promotion_submit_cases'](model_result())
        return 'native-thread'
    monkeypatch.setattr(runtime, 'run_project_agent', generate)
    if outcome == 'failed':
        with pytest.raises(RuntimeError):
            run(ctx, task)
    else:
        run(ctx, task)
    result = get(ctx, f"ai/tasks/{task['id']}")
    assert result['status'] == outcome
    command = next(row for row in result['activity']['items'] if row['detail'] == 'cat app.py')
    assert command['status'] == {'succeeded': 'completed', 'failed': 'failed', 'cancelled': 'stopped'}[outcome]
    assert 'DO NOT STORE' not in json.dumps(result)
    assert get(ctx, 'ai/tasks')['results'][0]['activity'] == result['activity']
    ctx['client'].force_authenticate(ctx['other'])
    assert get(ctx, 'ai/tasks')['results'] == []
    assert ctx['client'].get(f"{ctx['root']}/ai/tasks/{task['id']}").status_code == 404


def test_model_configuration_error_does_not_retry_forever(monkeypatch):
    task = SimpleNamespace(owner=None, snapshot={'request': {'instruction': '', 'project_path': '/project'}})
    monkeypatch.setattr(project_source, 'which', lambda _: 'git')
    monkeypatch.setattr(project_source, 'from_local', lambda *args: ({'app.py': {'text': 'def run(): pass', 'sha256': 'abc'}}, {}, {}))
    calls = []
    def broken(**kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            pytest.fail('Model failure retried as a read action')
        raise GenerationError('Invalid model configuration')
    with pytest.raises(RuntimeError):
        project_source.explore_project(task, broken, lambda _: None, lambda: None)
    assert len(calls) == 1


@pytest.mark.parametrize('focus', ['deployment', 'security', 'roadmap', 'application_overview', 'user', 'technical', 'business', 'all'])
def test_focus_api_roundtrip_and_idempotency(ctx, repo, monkeypatch, focus):
    payload = dict(kind='project', project_path=str(repo), exploration_focus=focus, request_key='focused-project')
    task = post(ctx, 'ai/tasks', payload, 202)
    assert task['request']['exploration_focus'] == focus
    assert post(ctx, 'ai/tasks', payload, 200)['id'] == task['id']
    post(ctx, 'ai/tasks', {**payload, 'exploration_focus': 'unknown'}, 400)
    post(ctx, 'ai/tasks', {**payload, 'exploration_focus': 'cost'}, 409)
    def generate(task, **kwargs):
        assert kwargs['content']['素材分类'] == project_source.allowed_material_types(focus)
        value = model_result()
        kind = focus if focus in MATERIAL_CATALOG else 'deployment'
        for item in value['cases']:
            item['data'].update(material_type=kind, summary='项目资料', facts='对应分类的项目事实')
        kwargs['handlers']['promotion_submit_cases'](value)
        return 'focused-thread'
    monkeypatch.setattr(runtime, 'run_project_agent', generate)
    run(ctx, task)
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    row = get(ctx, 'cases/' + applied['result']['case_ids'][0])
    assert row['data']['material_type'] == (focus if focus in MATERIAL_CATALOG else 'deployment')
    assert row['source_snapshot']['exploration_focus'] == focus
    assert patch(ctx, 'cases', row, {'status': 'confirmed'})['status'] == 'confirmed'


@pytest.mark.parametrize('focus', MATERIAL_CATALOG)
def test_concrete_focus_rejects_mixed_categories_and_allows_correction(focus):
    tools = project_source.ProjectTools({'exploration_focus': focus}, lambda _: None, lambda: None)
    definition = tools.definitions()[0]
    data_schema = definition['inputSchema']['properties']['cases']['items']['properties']['data']
    assert data_schema['properties']['material_type']['enum'] == [focus]
    assert 'material_type' in data_schema['required']
    value = model_result()
    for item in value['cases']:
        item['data']['material_type'] = focus
    if focus == 'overview':
        value['cases'] = value['cases'][:1]
    tools.submit(value)
    assert tools.result is not None
    if focus == 'overview':
        value['cases'].append({'title': '应用介绍', 'data': {'material_type': 'feature'}})
    value['cases'][1]['data']['material_type'] = 'overview' if focus != 'overview' else 'feature'
    with pytest.raises(ValidationError, match='本次仅允许素材分类'):
        tools.submit(value)
    assert tools.result is None
    assert value['cases'][1]['data']['material_type'] != focus
    value['cases'].pop()
    assert json.loads(tools.submit(value))['accepted']
    assert all(item['data']['material_type'] == focus for item in tools.result['cases'])
    assert json.loads(tools.submit({'insufficient_reason': '所选分类暂无资料'}))['insufficient_sources']
    assert tools.result is None


@pytest.mark.parametrize('focus', [None, *BROAD_FOCUSES])
def test_broad_or_legacy_focus_can_still_submit_multiple_categories(focus):
    source = {} if focus is None else {'exploration_focus': focus}
    tools = project_source.ProjectTools(source, lambda _: None, lambda: None)
    value = model_result()
    value['cases'][0]['data']['material_type'] = 'overview'
    value['cases'][1]['data']['material_type'] = 'feature'
    assert json.loads(tools.submit(value))['case_count'] == 2
    assert [item['data']['material_type'] for item in tools.result['cases']] == ['overview', 'feature']


def test_multi_category_request_roundtrip_validation_and_idempotency(ctx, repo, monkeypatch):
    payload = dict(kind='project', project_path=str(repo), exploration_mode='overview',
                   material_types=['deployment', 'security'], request_key='categories')
    task = post(ctx, 'ai/tasks', payload, 202)
    assert task['request']['material_types'] == ['deployment', 'security']
    assert post(ctx, 'ai/tasks', {**payload, 'material_types': ['security', 'deployment', 'security']}, 200)['id'] == task['id']
    post(ctx, 'ai/tasks', {**payload, 'material_types': ['deployment']}, 409)
    for invalid in [[], ['all'], ['unknown'], 'deployment']:
        post(ctx, 'ai/tasks', {**payload, 'material_types': invalid}, 400)

    def generate(task, **kwargs):
        assert kwargs['content']['素材分类'] == ['deployment', 'security']
        assert '本次素材分类' in kwargs['instruction']
        assert '综合视角' not in kwargs['instruction']
        schema = kwargs['tools'][0]['inputSchema']['properties']['cases']['items']['properties']['data']
        assert schema['properties']['material_type']['enum'] == ['deployment', 'security']
        value = model_result()
        for item, category in zip(value['cases'], ['deployment', 'feature']):
            item['data']['material_type'] = category
        with pytest.raises(ValidationError, match='deployment, security'):
            kwargs['handlers']['promotion_submit_cases'](value)
        value['cases'][1]['data']['material_type'] = 'security'
        kwargs['handlers']['promotion_submit_cases'](value)
        return 'multi-category-thread'

    monkeypatch.setattr(runtime, 'run_project_agent', generate)
    run(ctx, task)
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    rows = [get(ctx, 'cases/' + identifier) for identifier in applied['result']['case_ids']]
    assert [row['data']['material_type'] for row in rows] == ['deployment', 'security']
    assert all(row['source_snapshot']['material_types'] == ['deployment', 'security'] for row in rows)


def test_deep_exploration_ignores_overview_category_constraints(ctx, repo):
    payload = dict(kind='project', project_path=str(repo), exploration_mode='deep', instruction='部署流程',
                   material_types=['deployment'], exploration_focus='security', request_key='deep-categories')
    task = post(ctx, 'ai/tasks', payload, 202)
    assert 'material_types' not in task['request'] and 'exploration_focus' not in task['request']
    assert post(ctx, 'ai/tasks', {**payload, 'material_types': ['feature']}, 200)['id'] == task['id']


def test_project_overview_and_application_overviews_are_distinct_scopes():
    value = {'analysis': '一个项目包含两个应用', 'cases': [
        {'title': '创作平台整体介绍', 'data': {'material_type': 'overview'}},
        {'title': '项目宣传助手介绍', 'data': {'material_type': 'application_overview'}},
        {'title': '公众号写作助手介绍', 'data': {'material_type': 'application_overview'}},
    ]}
    result = project_source.validate_project_result(value, {'exploration_focus': 'all'})
    assert [row['data']['material_type'] for row in result['cases']] == ['overview', 'application_overview', 'application_overview']
    # A concrete selection cannot silently promote or demote the other scope.
    for focus in ['overview', 'application_overview']:
        with pytest.raises(ValidationError, match='本次仅允许素材分类'):
            project_source.validate_project_result(value, {'exploration_focus': focus})
    value['cases'][1]['data']['material_type'] = 'overview'
    with pytest.raises(ValidationError, match='项目概览应汇总整个项目'):
        project_source.validate_project_result(value, {'exploration_focus': 'all'})

import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError
from core.user_directories import user_directory
from app_center.project_promotion import runtime
from .. import project_source
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


def model_result(ids):
    return dict(analysis='Source-backed drafts; static reading only.', cases=[dict(title=title, evidence_ids=ids,
        data=dict(audience='创作者', problem='排版耗时', solution='格式化文章', implemented='输出 article 标签',
                  case_type='customer', assets=[dict(label='Invented', url='https://example.com/fake')]))
        for title in ['文章排版演示', '格式化实现记录']])


def project_model(monkeypatch):
    calls = []
    def generate(**kwargs):
        data = json.loads(kwargs['content']); calls.append(data)
        if '当前源码窗口' in data:
            step = sum('当前源码窗口' in c for c in calls)
            if step == 1:
                assert '5个选题' not in kwargs['instruction']
                return {'action': 'search', 'query': 'render'}
            if step == 2:
                assert data['上次动作结果']['matches']
                return {'action': 'read', 'path': 'app.py', 'start': 1}
            return {'action': 'finish', 'evidence_ids': [r['id'] for r in data['当前源码窗口'] if r['path'] == 'app.py']}
        return model_result([r['id'] for r in data['证据']])
    monkeypatch.setattr(runtime, 'generate_json', generate)
    return calls


def test_project_exploration_batch_apply_and_immutable_evidence(ctx, repo, monkeypatch):
    calls = project_model(monkeypatch)
    task = submit(ctx, repo)
    assert post(ctx, 'ai/tasks', dict(kind='project', project_path=str(repo), request_key='project'), 200)['id'] == task['id']
    run(ctx, task)
    task = get(ctx, f"ai/tasks/{task['id']}")
    assert task['status'] == 'succeeded' and task['stage']
    assert Case.objects.count() == 0
    serialized = json.dumps(calls)
    assert 'excluded-marker' not in serialized and 'ignored-marker' not in serialized
    assert 'Uncommitted working tree note' in serialized
    original = task['result']['cases'][0]['source_snapshot']
    evidence = next(iter(original['evidence'].values()))
    assert '<article>' in evidence['quote']
    assert evidence['sha256'] == hashlib.sha256((repo / 'app.py').read_bytes()).hexdigest()
    assert original['coverage']['exploration_rounds'] == 3
    assert original['origin']['working_tree'] is True
    (repo / 'app.py').write_text('changed after exploration', encoding='utf8')
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    assert Case.objects.count() == 2
    row = get(ctx, 'cases/' + applied['result']['case_ids'][0])
    assert row['status'] == 'draft' and row['data']['case_type'] == 'demo' and row['data']['assets'] == []
    assert '未运行' in row['data']['conditions']
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


@pytest.mark.parametrize('path', ['README.md', 'docs/guide.py', 'tests/test_app.py', 'api.d.ts', 'component.test.tsx', 'app.spec.js'])
def test_docs_tests_and_interfaces_cannot_prove_implementation(path):
    source = {'evidence': {'e1': dict(path=path, start=1, end=1, quote='planned feature', sha256='a' * 64)}}
    with pytest.raises(ValidationError):
        project_source.validate_project_result(model_result(['e1']), source)
    value = model_result(['e1'])
    for item in value['cases']:
        item['data']['implemented'] = ''
    assert project_source.validate_project_result(value, source)['cases'][0]['data']['implemented'] == ''


def test_unknown_citations_duplicates_and_insufficient_sources_are_rejected():
    source = {'evidence': {'e1': dict(path='app.py', start=1, end=1, quote='def render(): pass', sha256='a' * 64)}}
    with pytest.raises(ValidationError):
        project_source.validate_project_result(model_result(['forged']), source)
    value = model_result(['e1']); value['cases'][1]['title'] = value['cases'][0]['title']
    with pytest.raises(ValidationError):
        project_source.validate_project_result(value, source)
    with pytest.raises(ValueError, match='资料不足'):
        project_source.validate_project_result({'insufficient_reason': 'No implementation found'}, source)


def test_failed_generation_preserves_cases_and_can_retry(ctx, repo, monkeypatch):
    existing = case(ctx)
    calls = []
    def generate(**kwargs):
        data = json.loads(kwargs['content']); calls.append(data)
        if '当前源码窗口' in data:
            return {'action': 'finish', 'evidence_ids': [r['id'] for r in data['当前源码窗口']]}
        return model_result(['forged'])
    monkeypatch.setattr(runtime, 'generate_json', generate)
    task = submit(ctx, repo)
    with pytest.raises(RuntimeError):
        run(ctx, task)
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'failed'
    assert len([c for c in calls if '证据' in c]) == 2
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
    def cancel(**kwargs):
        sink.cancelled = True
        return {'action': 'finish', 'evidence_ids': []}
    monkeypatch.setattr(runtime, 'generate_json', cancel)
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
    monkeypatch.setattr(runtime, 'generate_json', lambda **kwargs: pytest.fail('Non-Git project reached model'))
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
    def generate(**kwargs):
        post(ctx, f"ai/tasks/{task['id']}/cancel", {}, 200)
        data = json.loads(kwargs['content'])
        if '当前源码窗口' in data:
            return {'action': 'finish', 'evidence_ids': [r['id'] for r in data['当前源码窗口']]}
        return model_result([r['id'] for r in data['证据']])
    monkeypatch.setattr(runtime, 'generate_json', generate)
    run(ctx, task)
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'cancelled'
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 404)
    assert get(ctx, 'cases')['results'][0]['id'] == existing['id']


def test_model_configuration_error_does_not_retry_forever(monkeypatch):
    task = SimpleNamespace(owner=None, snapshot={'request': {'instruction': '', 'project_path': '/project'}})
    monkeypatch.setattr(project_source, 'which', lambda _: 'git')
    monkeypatch.setattr(project_source, 'from_local', lambda *args: ({'app.py': {'text': 'def run(): pass', 'sha256': 'abc'}}, {}, {}))
    calls = []
    def broken(*args):
        calls.append(args)
        if len(calls) > 1:
            pytest.fail('Model failure retried as a read action')
        raise ValueError('Invalid model configuration')
    with pytest.raises(RuntimeError):
        project_source.explore_project(task, broken, lambda _: None, lambda: None)
    assert len(calls) == 1

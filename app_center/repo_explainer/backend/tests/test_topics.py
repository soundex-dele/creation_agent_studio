import copy
import json
import uuid

import pytest

from .test_repo import ctx, writing_skills, upload, finish, model, create_topics, Sink  # noqa: F401
from ..models import Task, Content, Project
from ..retrieval import retrieve
from ... import runtime


@pytest.mark.parametrize('direction', ['', '资料研究中的提问技巧'])
def test_topics_without_analysis_and_direction_reaches_retrieval(ctx, monkeypatch, direction):
    imported = upload(ctx); finish(imported)
    calls = []
    def capture(**kwargs):
        calls.append(kwargs)
        return model(**kwargs)
    monkeypatch.setattr(runtime, 'generate_json', capture)
    body = {'kind': 'topics', 'snapshot_id': str(imported.snapshot_id), 'direction': direction}
    response = ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='topics')
    assert response.status_code == 202, response.data
    task = Task.objects.get(pk=response.data['id']); result = finish(task)
    assert [topic['id'] for topic in result['topics']] == ['t1', 't2', 't3', 't4', 't5']
    assert result['evidence']['e2']['path'] == 'app.py'
    assert result['coverage']['files_read'] == 2
    assert not Task.objects.filter(kind='analyze').exists()
    assert not Content.objects.exists()
    assert all(json.loads(call['content'])['方向'] == direction for call in calls)
    same = ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='topics')
    assert same.data['id'] == str(task.id)
    changed = ctx.client.post(ctx.root + '/tasks', {**body, 'direction': 'different'}, format='json', HTTP_IDEMPOTENCY_KEY='topics')
    assert changed.status_code == 400
    new = ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='new-batch')
    assert new.data['id'] != str(task.id)
    task.refresh_from_db(); assert task.output == result


@pytest.mark.parametrize('topic_id', ['t1', 't2', 't3', 't4', 't5'])
@pytest.mark.parametrize('kind', ['video', 'image_text'])
def test_every_topic_writes_with_only_its_frozen_material(ctx, monkeypatch, topic_id, kind):
    topics = create_topics(ctx, monkeypatch, '资料研究')
    # Another topic has additional material which must not leak into this one.
    topics.output['evidence']['e_other'] = {'id': 'e_other', 'path': 'other.py', 'start': 1, 'end': 1, 'quote': 'other'}
    topics.save()
    calls = []
    def capture(**kwargs):
        calls.append(json.loads(kwargs['content']))
        return model(**kwargs)
    monkeypatch.setattr(runtime, 'generate_json', capture)
    body = {'kind': 'write', 'topic_task_id': str(topics.id), 'topic_id': topic_id, 'output': kind}
    response = ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='write')
    assert response.status_code == 202, response.data
    task = Task.objects.get(pk=response.data['id']); result = finish(task)
    content = Content.objects.get(pk=result['content_id'])
    assert content.analysis_id is None and content.topic_task_id == topics.id
    assert content.draft['kind'] == kind
    assert calls[0]['选题']['id'] == topic_id
    assert 'angle' not in calls[0]['要求']
    assert calls[0]['限定方向'] == '资料研究'
    assert set(calls[0]['证据']) == {'e2'}
    assert calls[0]['功能'] == []
    assert ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='write').data['id'] == str(task.id)
    finish(task); assert Content.objects.filter(generation=task).count() == 1
    data = ctx.client.get(ctx.root).data['contents'][0]
    assert data['analysis_id'] is None and data['topic_id'] == topic_id
    assert data['topic_task_id'] == str(topics.id)
    edited = copy.deepcopy(content.draft)
    edited['paragraphs'][0]['evidence_ids'] = ['e_other']
    assert ctx.client.put(ctx.root + f'/contents/{content.id}', {'revision': 1, 'document': edited}, format='json').status_code == 400
    edited['paragraphs'][0]['evidence_ids'] = []
    assert ctx.client.put(ctx.root + f'/contents/{content.id}', {'revision': 1, 'document': edited}, format='json').status_code == 400


@pytest.mark.parametrize('problem', ['missing_source', 'missing_topic', 'unknown_topic', 'legacy', 'override', 'unfinished', 'failed', 'cancelled', 'other_project', 'other_owner', 'other_organization'])
def test_write_rejects_invalid_or_inaccessible_source(ctx, monkeypatch, problem):
    topics = create_topics(ctx, monkeypatch)
    body = {'kind': 'write', 'topic_task_id': str(topics.id), 'topic_id': 't1'}
    expected = 400
    if problem == 'missing_source': body.pop('topic_task_id')
    elif problem == 'missing_topic': body.pop('topic_id')
    elif problem == 'unknown_topic': body['topic_id'] = 't6'
    elif problem == 'legacy': body = {'kind': 'write', 'analysis_id': str(topics.id), 'feature_ids': ['f1']}
    elif problem == 'override': body['evidence'] = {'e2': 'forged'}
    elif problem in {'unfinished', 'failed', 'cancelled'}:
        topics.run.status = 'running' if problem == 'unfinished' else problem
        topics.run.save(); expected = 404
    elif problem == 'other_owner':
        ctx.client.force_authenticate(ctx.other); expected = 404
    else:
        project = Project.objects.create(application=ctx.app, organization=ctx.org if problem == 'other_project' else ctx.other.owned_organizations.get(),
            owner=ctx.owner, title='其他项目')
        topics.project = project; topics.save(); expected = 404
    response = ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='write')
    assert response.status_code == expected, response.data
    assert not Task.objects.filter(kind='write').exists()


@pytest.mark.parametrize('problem', ['missing_snapshot', 'unknown_snapshot', 'long_direction', 'unfinished_import'])
def test_topic_input_validation(ctx, problem):
    imported = upload(ctx); finish(imported)
    body = {'kind': 'topics', 'snapshot_id': str(imported.snapshot_id)}
    expected = 400
    if problem == 'missing_snapshot': body.pop('snapshot_id')
    elif problem == 'unknown_snapshot': body['snapshot_id'] = str(uuid.uuid4()); expected = 404
    elif problem == 'long_direction': body['direction'] = 'a' * 2001
    else: imported.run.status = 'running'; imported.run.save()
    assert ctx.client.post(ctx.root + '/tasks', body, format='json', HTTP_IDEMPOTENCY_KEY='topics').status_code == expected


@pytest.mark.parametrize('problem', ['forged_reference', 'empty_reference', 'duplicate', 'insufficient', 'cancelled'])
def test_topic_generation_failure_does_not_publish_results(ctx, monkeypatch, problem):
    imported = upload(ctx); finish(imported)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'topics', 'snapshot_id': str(imported.snapshot_id)},
        format='json', HTTP_IDEMPOTENCY_KEY='topics')
    task = Task.objects.get(pk=response.data['id'])
    attempts = []
    def bad(**kwargs):
        value = model(**kwargs)
        if 'topics' in value:
            attempts.append(1)
            if problem == 'forged_reference': value['topics'][0]['evidence_ids'] = ['fake']
            elif problem == 'empty_reference': value['topics'][0]['evidence_ids'] = []
            elif problem == 'duplicate': value['topics'][1]['title'] = value['topics'][0]['title']
            elif problem == 'insufficient': return {'insufficient_reason': '没有该方向的实现依据'}
        return value
    monkeypatch.setattr(runtime, 'generate_json', bad)
    sink = Sink(); sink.cancelled = problem == 'cancelled'
    with pytest.raises(InterruptedError if sink.cancelled else ValueError): finish(task, sink)
    task.refresh_from_db()
    assert 'topics' not in task.output
    assert len(attempts) == (0 if sink.cancelled else 1 if problem == 'insufficient' else 2)
    assert not Content.objects.exists()


def test_retrieval_honors_budget_and_direction(settings):
    settings.REPO_EXPLAINER_ANALYSIS_CHARS = 150
    settings.REPO_EXPLAINER_ROUNDS = 1
    files = {'README.md': {'text': 'tool overview'}, 'search.py': {'text': 'def search(): pass' * 6},
             'large.py': {'text': 'x' * 13000}}
    def queries(instruction, data):
        assert data['方向'] == '搜索'
        return {'queries': ['search.py']}
    evidence, coverage = retrieve(files, queries, lambda _: None, '搜索')
    assert {row['path'] for row in evidence.values()} == {'README.md', 'search.py'}
    assert coverage['characters_read'] <= 150 and coverage['incomplete']


def test_previously_queued_legacy_write_still_saves_and_exports(ctx, monkeypatch):
    from ..views import start
    from ..serializers import TaskInput
    monkeypatch.setattr(runtime, 'generate_json', model)
    imported = upload(ctx); finish(imported)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'analyze', 'snapshot_id': str(imported.snapshot_id)},
        format='json', HTTP_IDEMPOTENCY_KEY='analysis')
    analysis = Task.objects.get(pk=response.data['id']); finish(analysis)
    options = {key: field.default for key, field in TaskInput().fields.items() if key in {'angle', 'output', 'audience', 'style', 'duration', 'aspect'}}
    options.update(kind='write', analysis_id=str(analysis.id), feature_ids=['f1'])
    task = start(ctx.project, ctx.owner, analysis.snapshot, 'write', options, 'old-queued', 'hash')
    content = Content.objects.get(pk=finish(task)['content_id'])
    assert content.analysis_id == analysis.id and content.topic_task_id is None
    edited = copy.deepcopy(content.draft); edited['title'] = '旧作品编辑'
    response = ctx.client.put(ctx.root + f'/contents/{content.id}', {'revision': 1, 'document': edited}, format='json')
    assert response.status_code == 200 and response.data['revision'] == 2
    assert ctx.client.get(ctx.root + f'/contents/{content.id}/download').status_code == 200


@pytest.mark.parametrize('cancel', [False, True])
def test_topic_runtime_explores_until_model_finishes_or_user_cancels(ctx, monkeypatch, settings, cancel):
    settings.REPO_EXPLAINER_ROUNDS = 1
    imported = upload(ctx); finish(imported)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'topics', 'snapshot_id': str(imported.snapshot_id)},
        format='json', HTTP_IDEMPOTENCY_KEY='autonomous')
    task = Task.objects.get(pk=response.data['id'])
    calls, events = [], []
    sink = Sink()
    sink.emit = lambda kind, payload: events.append(payload)
    def autonomous(**kwargs):
        if '"action":"finish"' in kwargs['instruction']:
            calls.append(kwargs)
            if len(calls) == 7:
                sink.cancelled = cancel
                return {'action': 'finish', 'evidence_ids': ['e2']}
            return {'action': 'read', 'path': 'app.py', 'notes': 'private source notes'}
        return model(**kwargs)
    monkeypatch.setattr(runtime, 'generate_json', autonomous)
    if cancel:
        with pytest.raises(InterruptedError): finish(task, sink)
        task.refresh_from_db()
        assert 'topics' not in task.output
    else:
        result = finish(task, sink)
        assert len(result['topics']) == 5 and result['coverage']['exploration_rounds'] == 7
    assert len(calls) == 7
    assert any('第7轮' in event.get('stage', '') for event in events)
    assert 'private source notes' not in json.dumps(events)

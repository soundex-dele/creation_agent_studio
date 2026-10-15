import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from rest_framework.exceptions import ValidationError

from ..ai import validate_result
from ..models import AITask
from .test_promotion import ctx, post, case, execute
from .test_project_source import repo, project_model, run


@pytest.mark.parametrize('kind', ['topics', 'review'])
def test_topic_preferences_reach_generation_and_retries(ctx, monkeypatch, kind):
    source = case(ctx)
    options = dict(direction='application_overview', audience='开发者与技术团队', platform='wechat', count=3)
    payload = dict(kind=kind, case_ids=[source['id']], request_key='preferences', topic_options=options)
    task = post(ctx, 'ai/tasks', payload, 202)
    assert task['request']['topic_options'] == options
    assert post(ctx, 'ai/tasks', payload, 200)['id'] == task['id']
    post(ctx, 'ai/tasks', {**payload, 'topic_options': {**options, 'count': 5}}, 409)
    captured = execute(ctx, task, monkeypatch, {'topics': [{'title': '应用介绍', 'data': {'direction': 'application_overview'}}]})
    assert json.loads(captured['content'])['request']['topic_options'] == options
    assert 'request.topic_options' in captured['instruction']
    assert '不能替代已选项目素材' in captured['instruction']
    assert AITask.objects.get(pk=task['id']).status == 'succeeded'


@pytest.mark.parametrize('options', [{'count': 0}, {'count': 13}, {'direction': 'invalid'},
    {'platform': 'invalid'}, {'audience': 'a' * 201}, {'unknown': True}, None])
def test_invalid_preferences_rejected_before_generation(ctx, options):
    source = case(ctx)
    post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[source['id']], request_key='invalid', topic_options=options), 400)
    assert AITask.objects.count() == 0


@pytest.mark.parametrize('kind', ['case', 'project', 'copy'])
def test_preferences_are_only_for_topic_generation(ctx, kind):
    post(ctx, 'ai/tasks', dict(kind=kind, request_key='invalid', topic_options={'count': 3}), 400)


@pytest.mark.parametrize('kind', ['topics', 'review'])
def test_result_respects_requested_limit_but_allows_fewer_topics(kind):
    source = str(uuid4())
    task = SimpleNamespace(kind=kind, snapshot={'request': {'topic_options': {'count': 1}}, 'cases': [{'id': source}]})
    idea = {'title': '功能介绍', 'data': {}}
    assert len(validate_result(task, {'topics': [idea]})['topics']) == 1
    with pytest.raises(ValidationError, match='上限'):
        validate_result(task, {'topics': [idea, idea]})
    task.snapshot['request']['topic_options']['count'] = 3
    assert len(validate_result(task, {'topics': [idea]})['topics']) == 1


def test_material_extraction_ignores_old_brand_selection_and_snapshot(ctx, monkeypatch):
    payload = dict(kind='case', instruction='已实现导出功能', request_key='material', brand_reference={'profile_id': 'unavailable'})
    task = post(ctx, 'ai/tasks', payload, 202)
    assert task['request']['brand_reference'] is None
    stored = AITask.objects.get(pk=task['id'])
    assert 'brand' not in stored.snapshot
    assert post(ctx, 'ai/tasks', {**payload, 'brand_reference': None}, 200)['id'] == task['id']
    # Already queued tasks may have snapshots created before this change.
    stored.snapshot['brand'] = {'context': '旧品牌资料'}
    stored.snapshot['request']['brand_reference'] = {'profile_id': 'old'}
    stored.save()
    captured = execute(ctx, task, monkeypatch, {'title': '导出功能', 'data': {'material_type': 'feature'}})
    content = json.loads(captured['content'])
    assert 'brand' not in content and 'brand_reference' not in content['request']
    stored.refresh_from_db()
    assert stored.snapshot['brand']['context'] == '旧品牌资料'


def test_project_exploration_has_no_brand_context(ctx, repo, monkeypatch):
    calls = project_model(monkeypatch)
    task = post(ctx, 'ai/tasks', dict(kind='project', project_path=str(repo), request_key='project-no-brand',
        brand_reference={'profile_id': 'unavailable'}), 202)
    assert task['request']['brand_reference'] is None
    stored = AITask.objects.get(pk=task['id'])
    assert 'brand' not in stored.snapshot
    stored.snapshot['brand'] = {'context': '旧品牌资料'}
    stored.save()
    run(ctx, task)
    assert len(calls) == 1
    assert '品牌资料' not in calls[0]['content']

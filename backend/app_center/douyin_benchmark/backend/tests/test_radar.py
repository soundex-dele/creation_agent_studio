from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from .. import models as m
from ..radar import collect, validate_topics
from ..provider import CollectionError
from ...radar_source import parse_hotlist, parse_search, search_failure
from ...runtime import execute
from .test_douyin import ctx, claim  # noqa: F401
from .test_research import start, finish, scope_for


def source(index=1):
    return {'id': f'work:{index}', 'kind': 'work', 'title': f'科学问题{index}', 'author': '科普作者',
            'url': f'https://www.douyin.com/?modal_id={index}', 'captured_at': '2026-10-10T00:00:00Z', 'likes': 0}


def collected(ctx):
    response = start(ctx, {'kind': 'radar_search', 'keyword': '科普'}, 'scan')
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    task.output = {'radar_items': [source()], 'keyword': '科普'}
    task.save()
    finish(task)
    return task


def test_parsers_preserve_rank_zero_missing_and_safe_links():
    assert search_failure({'status_code': 2483, 'status_msg': '请登录后再搜索'}) == 'auth'
    assert search_failure({'status_code': 999, 'status_msg': 'unknown'}) == 'search_unavailable'
    hot = parse_hotlist({'data': {'word_list': [{'word': '科学/问题', 'position': 8, 'hot_value': 0}]}}, 'now')['items'][0]
    assert hot['rank'] == 8 and hot['heat'] == 0 and '%2F' in hot['url']
    payload = {'data': [{'aweme_info': {'aweme_id': '123', 'desc': '科学', 'author': {'nickname': '作者'},
               'statistics': {'digg_count': 0, 'comment_count': -1}, 'video': {'url': 'secret'}}}], 'has_more': 0}
    row = parse_search(payload, 'now')['items'][0]
    assert row['likes'] == 0 and row['comments'] is None and row['shares'] is None
    assert row['url'] == 'https://www.douyin.com/?modal_id=123'
    assert 'secret' not in str(row)
    assert parse_search({'data': [], 'has_more': 0}, 'now')['items'] == []
    assert parse_hotlist({'data': {'word_list': []}}, 'now')['items'] == []
    with pytest.raises(ValueError): parse_search({'data': [{'unexpected': True}], 'has_more': 0}, 'now')
    with pytest.raises(ValueError): parse_hotlist({'data': {}}, 'now')


def run_collection(monkeypatch, responses, check=lambda: None):
    fetch = Mock(side_effect=responses)
    monkeypatch.setattr('app_center.douyin_benchmark.backend.radar.LocalDTKClient', lambda **kw: SimpleNamespace(fetch=fetch))
    snapshots = []
    task = SimpleNamespace(kind='radar_search', input={'keyword': '科学'}, application=None, owner=None)
    collect(task, lambda stage, output=None, **kw: snapshots.append((stage, deepcopy(output))), check)
    return fetch, snapshots


def page(items, more=True, cursor='20'):
    return {'items': items, 'has_more': more, 'cursor': cursor, 'captured_at': 'now'}


def test_pagination_dedup_and_stall(monkeypatch):
    fetch, saved = run_collection(monkeypatch, [page([source()]), page([source(), source(2)])])
    assert fetch.call_count == 2 and len(saved[-1][1]['radar_items']) == 2
    assert saved[-1][0] == 'partial' and '分页' in saved[-1][1]['warning']


@pytest.mark.parametrize('code', ['timeout', 'limited', 'auth', 'challenge', 'invalid'])
def test_partial_failure_and_first_page_failure(monkeypatch, code):
    _, saved = run_collection(monkeypatch, [page([source()]), CollectionError(code)])
    assert saved[-1][0] == 'partial' and saved[-1][1]['radar_items'] == [source()]
    with pytest.raises(CollectionError): run_collection(monkeypatch, [CollectionError(code)])


def test_bounds_and_cancel(monkeypatch):
    fetch, saved = run_collection(monkeypatch, [page([source(i) for i in range(n * 20, n * 20 + 20)], cursor=str(n + 1)) for n in range(5)])
    assert fetch.call_count == 3 and len(saved[-1][1]['radar_items']) == 50
    fetch, saved = run_collection(monkeypatch, [page([source(n)], cursor=str(n + 1)) for n in range(5)])
    assert fetch.call_count == 5 and '5页' in saved[-1][1]['warning']
    with pytest.raises(InterruptedError): run_collection(monkeypatch, [], Mock(side_effect=InterruptedError()))


def test_no_accounts_collect_execute_history_and_retry_contract(ctx, monkeypatch):
    ctx.account.delete()
    response = start(ctx, {'kind': 'radar_hotlist'})
    assert response.status_code == 201, response.data
    assert start(ctx, {'kind': 'radar_hotlist'}).data['id'] == response.data['id']
    assert start(ctx, {'kind': 'radar_search', 'keyword': '不同'}).status_code == 409
    task = m.Task.objects.get(pk=response.data['id'])
    monkeypatch.setattr('app_center.douyin_benchmark.backend.radar.LocalDTKClient', lambda **kw: SimpleNamespace(fetch=lambda *args: page([source()], False)))
    execute(*claim(task))
    task.refresh_from_db()
    assert task.output['radar_items'] == [source()]
    rows = ctx.client.get(ctx.root + '/tasks?kind=radar_hotlist,radar_search,radar_topics').data['results']
    assert len(rows) == 1 and rows[0]['output']['radar_request'] == {'kind': 'radar_hotlist'}
    assert ctx.client.get(ctx.root + '/tasks?exclude_kind=radar_hotlist,radar_search,radar_topics').data['count'] == 0
    assert not m.Account.objects.exists() and not m.Work.objects.exists()


def test_source_validation_and_private_snapshots(ctx, monkeypatch):
    original = collected(ctx)
    body = {'kind': 'radar_topics', 'source_task_id': str(original.pk), 'source_ids': ['work:1']}
    assert start(ctx, {**body, 'source_ids': ['fake']}, 'bad').status_code == 400
    assert start(ctx, {**body, 'source_ids': []}, 'empty').status_code == 400
    assert start(ctx, {'kind': 'radar_search', 'keyword': ' '}, 'empty-search').status_code == 400
    original.run.status = 'cancelled'; original.run.save()
    assert start(ctx, body, 'cancelled-source').status_code == 404
    finish(original)
    ctx.client.force_authenticate(ctx.reader)
    assert start(ctx, body, 'foreign').status_code == 404
    assert ctx.client.get(ctx.root + f'/tasks/{original.pk}').status_code == 404
    ctx.client.force_authenticate(ctx.owner)
    result = start(ctx, body, 'suggest')
    assert result.status_code == 201, result.data
    task = m.Task.objects.get(pk=result.data['id'])
    original.output['radar_items'][0]['title'] = '修改'
    original.save()
    assert task.input['radar_items'][0]['title'] == '科学问题1'
    topics = {'topics': [{**{k: f'建议{i}' for k in ('title', 'angle', 'hook', 'reason', 'materials_needed')}, 'refs': ['work:1']} for i in range(3)]}
    model = Mock(return_value=topics)
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    execute(*claim(task))
    task.refresh_from_db()
    assert task.output['topics'] == topics['topics'] and task.output['radar_items'][0]['title'] == '科学问题1'
    assert model.call_count == 1
    finish(task)
    idea = ctx.client.post(ctx.root + '/ideas', {'title': '建议', 'notes': source()['url'], 'source_task': str(task.pk)}, format='json')
    assert idea.status_code == 201 and str(idea.data['source_task']) == str(task.pk)
    assert validate_topics(topics, {'work:1'}) == topics
    topics['topics'][0]['refs'] = ['made-up']
    with pytest.raises(ValueError): validate_topics(topics, {'work:1'})


def test_optional_owned_positioning_frozen_and_required_when_selected(ctx):
    original = collected(ctx)
    ctx.account.is_owned = True
    ctx.account.save()
    body = {'kind': 'radar_topics', 'source_task_id': str(original.pk), 'source_ids': ['work:1'], 'target_account_id': str(ctx.account.pk)}
    assert start(ctx, body, 'missing').status_code == 400
    profile = m.CreatorProfile.objects.create(**scope_for(ctx.app, ctx.owner), account=ctx.account, name='我', positioning='科学', audience='学生', content_boundaries='不编造')
    response = start(ctx, body, 'personal')
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    profile.positioning = '修改'; profile.save()
    assert task.input['radar_profile']['positioning'] == '科学'
    assert task.input['radar_profile']['content_boundaries'] == '不编造'

import json
from uuid import uuid4
from types import SimpleNamespace
import pytest
from rest_framework.exceptions import ValidationError
from ..ai import validate_result
from ..models import AITask, Case, Topic
from ..catalog import MATERIAL_TYPES
from .test_promotion import ctx, post, get, patch, case, channel, version, publish, execute


def material(c, kind='feature'):
    return post(c, 'cases', dict(title=f'{kind}资料', status='confirmed', data=dict(material_type=kind,
        summary='项目资料摘要', facts='README 声明的设计与使用条件，未运行验证')))


@pytest.mark.parametrize('kind', [kind for kind in MATERIAL_TYPES if kind != 'case'])
def test_materials_confirm_with_facts_without_case_fields(ctx, kind):
    row = material(ctx, kind)
    assert row['data']['problem'] == '' and row['data']['implemented'] == ''
    patch(ctx, 'cases', row, {'data': {'facts': ''}}, 400)
    assert get(ctx, f"cases/{row['id']}")['revision'] == row['revision']


def test_case_confirmation_does_not_require_evidence(ctx):
    row = post(ctx, 'cases', dict(title='排版案例', status='confirmed', data=dict(
        audience='创作者', problem='重复排版', solution='自动排版', implemented='输出 HTML')))
    assert row['status'] == 'confirmed' and row['data']['evidence'] == ''
    patch(ctx, 'cases', row, {'data': {'implemented': ''}}, 400)


def test_generation_context_preserves_manual_notes_and_original_snapshots():
    from ..materials import generation_context
    legacy = {'case': {'data': {'evidence': 'app.py:1'}, 'source_snapshot': {'evidence': {'e1': {'quote': 'code'}}}}}
    clean = generation_context(legacy)
    assert clean == {'case': {'data': {}}}
    assert legacy['case']['data']['evidence'] == 'app.py:1'
    assert generation_context({'case': {'data': {'evidence': '用户提供的产出说明'}}})['case']['data']['evidence'] == '用户提供的产出说明'


def test_legacy_case_and_topic_remain_readable(ctx):
    row = case(ctx)
    # Historical JSON has no newly introduced fields, and historical topics have no join rows.
    record = Case.objects.get(pk=row['id'])
    for key in ('material_type', 'summary', 'facts'):
        record.data.pop(key)
    record.save()
    old = Topic.objects.create(organization=ctx['org'], application=ctx['app'], owner=ctx['user'],
        case=record, title='历史选题', status='confirmed')
    assert get(ctx, f'topics/{old.pk}')['case_ids'] == [row['id']]
    patch(ctx, 'cases', row, {'title': '旧案例继续编辑'})
    assert get(ctx, f"cases/{row['id']}")['data']['material_type'] == 'case'
    publish(ctx, channel(ctx, get(ctx, f'topics/{old.pk}')))


def test_multi_source_edit_validation_and_private_scope(ctx):
    first, second = case(ctx), material(ctx)
    row = post(ctx, 'topics', dict(title='完整流程', case_ids=[first['id'], second['id']], status='confirmed'))
    assert row['case_ids'] == [first['id'], second['id']]
    # An old client echoing case_id must not silently erase additional sources.
    row = patch(ctx, 'topics', row, {'case_id': first['id'], 'title': '新标题'})
    assert len(row['case_ids']) == 2
    patch(ctx, 'topics', row, {'case_ids': []}, 400)
    patch(ctx, 'topics', row, {'case_ids': [second['id']], 'case_id': first['id']}, 400)
    archived = patch(ctx, 'cases', second, {'archived': True})
    patch(ctx, 'topics', row, {'status': 'confirmed'}, 400)
    post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[first['id'], second['id']], request_key='archived'), 400)
    patch(ctx, 'cases', archived, {'archived': False})
    ctx['client'].force_authenticate(ctx['other'])
    own = material(ctx)
    post(ctx, 'topics', dict(title='越权引用', case_ids=[own['id'], second['id']]), 404)
    post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[own['id'], second['id']], request_key='private'), 404)
    ctx['client'].force_authenticate(ctx['user'])
    row = patch(ctx, 'topics', row, {'case_ids': [second['id']]})
    assert row['case_ids'] == [second['id']] and row['case_id'] == second['id']


def test_generation_keeps_each_topics_actual_sources_and_rejects_stale_apply(ctx, monkeypatch):
    first, second = case(ctx), material(ctx)
    task = post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[first['id'], second['id']], request_key='multi'), 202)
    captured = execute(ctx, task, monkeypatch, {'analysis': '多角度', 'topics': [
        {'title': '项目全貌', 'case_ids': [first['id'], second['id']], 'data': {'direction': 'overview', 'thesis': '核心观点', 'outline': '内容结构'}},
        {'title': '功能设计', 'case_ids': [second['id']], 'data': {'direction': 'architecture'}}]})
    assert len(json.loads(captured['content'])['cases']) == 2
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    ids = applied['result']['topic_ids']
    assert get(ctx, f'topics/{ids[0]}')['case_ids'] == [first['id'], second['id']]
    assert get(ctx, f'topics/{ids[1]}')['case_ids'] == [second['id']]
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    assert Topic.objects.count() == 2
    next_task = post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[second['id']], request_key='stale'), 202)
    execute(ctx, next_task, monkeypatch, {'topics': [{'title': '旧依据', 'data': {}}]})
    patch(ctx, 'cases', second, {'data': {'facts': '变更后的事实'}})
    post(ctx, f"ai/tasks/{next_task['id']}/apply", {}, 409)
    assert not AITask.objects.get(pk=next_task['id']).applied


@pytest.mark.parametrize('ids', [None, [], ['foreign']])
def test_multi_source_generation_requires_valid_source_ids(ids):
    one, two = str(uuid4()), str(uuid4())
    task = SimpleNamespace(kind='topics', snapshot={'cases': [{'id': one}, {'id': two}]})
    result = {'title': '选题', 'data': {}}
    if ids is not None:
        result['case_ids'] = [str(uuid4())] if ids == ['foreign'] else ids
    with pytest.raises(ValidationError):
        validate_result(task, {'topics': [result]})


def test_secondary_material_changes_block_confirm_and_publish(ctx):
    first, second = case(ctx), material(ctx)
    idea = post(ctx, 'topics', dict(title='全貌', case_ids=[first['id'], second['id']], status='confirmed'))
    row = channel(ctx, idea)
    v = version(ctx, row)
    assert len(v['snapshot']['cases']) == 2
    row = get(ctx, f"channels/{row['id']}")
    second = patch(ctx, 'cases', second, {'data': {'facts': '新事实'}})
    post(ctx, f"channels/{row['id']}/versions/{v['id']}/confirm", {'revision': row['revision']}, 409)
    v = version(ctx, row)
    row = get(ctx, f"channels/{row['id']}")
    row = post(ctx, f"channels/{row['id']}/versions/{v['id']}/confirm", {'revision': row['revision']}, 200)
    second = patch(ctx, 'cases', second, {'archived': True})
    patch(ctx, 'channels', row, {'status': 'published', 'data': {'published_at': '2026-10-14T12:00:00+08:00'}}, 400)
    post(ctx, 'ai/tasks', dict(kind='copy', channel_id=row['id'], request_key='archived-copy'), 400)
    patch(ctx, 'cases', second, {'archived': False})
    patch(ctx, 'channels', row, {'status': 'published', 'data': {'published_at': '2026-10-14T12:00:00+08:00'}}, 409)


def test_report_uses_published_sources_and_does_not_double_count_channels(ctx):
    first, second = case(ctx), material(ctx)
    idea = post(ctx, 'topics', dict(title='全貌', case_ids=[first['id'], second['id']], status='confirmed'))
    row = publish(ctx, channel(ctx, idea))
    post(ctx, 'feedback', dict(title='观察', channel_id=row['id'], data={'observed_on': '2026-10-14', 'views': 100}))
    patch(ctx, 'topics', idea, {'case_ids': [second['id']]})
    stats = get(ctx, 'report')
    assert len(stats['groups']['cases']) == 2
    assert all(g['metrics']['views']['total'] == 100 for g in stats['groups']['cases'])
    assert stats['groups']['platforms'][0]['metrics']['views']['total'] == 100
    assert stats['publications'][0]['case_ids'] == [first['id'], second['id']]
    assert '不可相加' in stats['note']


def test_legacy_version_snapshot_still_confirms(ctx):
    from ..models import Version
    first = case(ctx)
    idea = post(ctx, 'topics', dict(title='历史选题', case_id=first['id'], status='confirmed'))
    row = channel(ctx, idea)
    saved = version(ctx, row)
    old = Version.objects.get(pk=saved['id'])
    old.snapshot.pop('cases')
    old.snapshot['topic'].pop('case_ids')
    old.save()
    row = get(ctx, f"channels/{row['id']}")
    post(ctx, f"channels/{row['id']}/versions/{saved['id']}/confirm", {'revision': row['revision']}, 200)


def test_project_materials_support_documented_designs_and_twelve_distinct_facts():
    from ..project_source import validate_project_result
    source = {'origin': {'path': '/project'}}
    items = [{'title': f'设计资料 {i}', 'data': {
        'material_type': 'architecture', 'summary': '设计资料', 'facts': 'README 中声明的设计，未运行验证'}} for i in range(12)]
    result = validate_project_result({'analysis': '仅覆盖文档设计，缺少运行产物', 'cases': items}, source)
    assert len(result['cases']) == 12
    assert all(row['data']['implemented'] == '' and row['data']['material_type'] == 'architecture' for row in result['cases'])
    assert all(row['data']['evidence'] == '' for row in result['cases'])


def test_secondary_material_from_another_organization_is_rejected(ctx):
    second_org = ctx['other'].owned_organizations.get()
    foreign = Case.objects.create(organization=second_org, application=ctx['app'], owner=ctx['user'],
        title='跨组织素材', status='confirmed')
    first = case(ctx)
    post(ctx, 'topics', dict(title='跨组织选题', case_ids=[first['id'], str(foreign.pk)]), 404)
    post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[first['id'], str(foreign.pk)], request_key='cross-org'), 404)


def test_copy_generation_and_apply_snapshot_include_all_materials(ctx, monkeypatch):
    first, second = case(ctx), material(ctx)
    idea = post(ctx, 'topics', dict(title='完整工作流', case_ids=[first['id'], second['id']], status='confirmed'))
    row = channel(ctx, idea)
    task = post(ctx, 'ai/tasks', dict(kind='copy', channel_id=row['id'], request_key='copy'), 202)
    captured = execute(ctx, task, monkeypatch, {'title': '完整流程', 'body': '组合资料'})
    assert {item['id'] for item in json.loads(captured['content'])['cases']} == {first['id'], second['id']}
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    snapshots = get(ctx, f"channels/{row['id']}/versions")[0]['snapshot']['cases']
    assert {item['id'] for item in snapshots} == {first['id'], second['id']}


def test_compatibility_alias_does_not_double_count_source_limits_or_handoffs(ctx, monkeypatch):
    from apps.applications.models import Application, ChatApplication
    first, second = case(ctx), material(ctx)
    record = Case.objects.get(pk=second['id'])
    record.source_snapshot = {'evidence': {'e1': {'quote': 'a' * 45000}}}
    record.save()
    idea = post(ctx, 'topics', dict(title='设计解读', case_ids=[second['id'], first['id']], status='confirmed'))
    row = channel(ctx, idea)
    saved = version(ctx, row)
    target = Application.objects.create(organization=ctx['org'], category=ctx['app'].category, name='图文',
        slug='write-image-text-copy', created_by=ctx['user'], kind='chat', visibility='organization')
    ChatApplication.objects.create(application=target)
    handoff = post(ctx, 'handoffs', dict(channel_id=row['id'], version_id=saved['id'], target_id=target.pk))
    source = json.loads(handoff['draft']['source'])['source']
    assert {item['id'] for item in source['cases']} == {first['id'], second['id']}
    assert len(handoff['draft']['source']) < 75000
    assert saved['snapshot']['case']['id'] == second['id']
    # A single previously valid large material still fits the task input limit.
    record.source_snapshot['evidence']['e1']['quote'] = 'b' * 100000
    record.save()
    task = post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[second['id']], request_key='large'), 202)
    captured = execute(ctx, task, monkeypatch, {'topics': [{'title': '设计选题', 'data': {}}]})
    assert len(captured['content']) < 180000
    sent = json.loads(captured['content'])['cases'][0]
    assert 'source_snapshot' not in sent and 'evidence' not in sent['data']
    record.refresh_from_db()
    assert record.source_snapshot['evidence']['e1']['quote'] == 'b' * 100000
    assert saved['snapshot']['cases'][0]['source_snapshot']['evidence']['e1']['quote'] == 'a' * 45000
    assert 'source_snapshot' not in source['cases'][0]


def test_application_overview_retains_its_scope_when_planning_topics(ctx, monkeypatch):
    source = material(ctx, 'application_overview')
    task = post(ctx, 'ai/tasks', dict(kind='topics', case_ids=[source['id']], request_key='application-introduction'), 202)
    captured = execute(ctx, task, monkeypatch, {'topics': [{'title': '项目宣传助手介绍', 'data': {'direction': 'application_overview'}}]})
    assert json.loads(captured['content'])['cases'][0]['data']['material_type'] == 'application_overview'
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    topic = get(ctx, 'topics/' + applied['result']['topic_ids'][0])
    assert topic['data']['direction'] == 'application_overview'
    assert topic['case_ids'] == [source['id']]

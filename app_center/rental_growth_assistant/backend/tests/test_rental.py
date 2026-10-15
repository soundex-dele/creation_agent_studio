import json
from copy import deepcopy
from uuid import uuid4
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from modules.execution.models import Run
from app_center.rental_growth_assistant import runtime
from .. import ai
from ..models import AITask, Property, Content, ContentVersion, Lead, Preferences, Persona


@pytest.fixture
def ctx(db, monkeypatch):
    user = get_user_model().objects.create_user(username='rental-user')
    other = get_user_model().objects.create_user(username='rental-other')
    org = user.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role=Membership.Role.VIEWER)
    cat = ApplicationCategory.objects.create(name='Rental', slug='rental')
    app = Application.objects.create(organization=org, category=cat, name='租房获客助手', slug='rental-growth-assistant',
                                    created_by=user, kind='custom', visibility='organization')
    client = APIClient(); client.force_authenticate(user)
    def start(**kwargs):
        return Run.objects.create(organization=org, owner=kwargs['actor'], source_type='application', source_id=str(app.pk),
            executor_kind='media', executor_key='rental-growth-assistant', input=kwargs['input_data']), False
    monkeypatch.setattr(ai, 'start_application_run', start)
    return dict(client=client, app=app, org=org, user=user, other=other,
                root=f'/api/v1/organizations/{org.pk}/applications/{app.pk}/rental-growth-assistant')


def post(ctx, path, value, status=201):
    response = ctx['client'].post(f"{ctx['root']}/{path}", value, format='json')
    assert response.status_code == status, response.data
    return response.data


def get(ctx, path, **params):
    response = ctx['client'].get(f"{ctx['root']}/{path}", params)
    assert response.status_code == 200, response.data
    return response.data


def patch(ctx, kind, row, value, status=200):
    response = ctx['client'].patch(f"{ctx['root']}/{kind}/{row['id']}", {'revision': row['revision'], **value}, format='json')
    assert response.status_code == status, response.data
    return response.data


def prop(ctx, **changes):
    data = dict(city='上海', district='徐汇', rent=2800, rental_type='whole', layout='一室一厅', pets='yes', elevator='yes',
                available_from='2026-10-01', drawbacks='临街有噪声', photos=[dict(label='客厅', note='实拍')])
    data.update(changes)
    return post(ctx, 'properties', dict(title='梧桐公寓', data=data))


def lead(ctx, **data):
    return post(ctx, 'leads', dict(title='小林', data=dict(consulted_on='2026-10-05', **data)))


def task(ctx, kind='copy', **values):
    return post(ctx, 'ai/tasks', dict(kind=kind, request_key=str(uuid4()), **values), 202)


class Sink:
    cancelled = False
    def emit(self, *args): pass


def execute(ctx, data, monkeypatch, result):
    model = AITask.objects.get(pk=data['id'])
    monkeypatch.setattr(runtime, 'call_model', lambda *args: result)
    runtime.execute(dict(run_id=str(model.run_id), organization_id=str(ctx['org'].pk), input={'task_id': str(model.pk)}), Sink())
    return get(ctx, f"ai/tasks/{model.pk}")


def copy_result(property_id=None):
    return dict(titles=['真实房源推荐', '独居选房', '费用说清楚'], cover='一室一厅', body='月租2800元，临街有噪声。',
                pages=[dict(photo_ref=f'{property_id}:1' if property_id else '', caption='客厅', layout='如果顶部有留白，可放标题')])


def initialize_personas(ctx):
    response = ctx['client'].put(f"{ctx['root']}/personas/built-ins", {}, format='json')
    assert response.status_code == 200, response.data
    return response.data


def test_builtin_personas_are_complete_and_used_in_generation_snapshot(ctx):
    assert initialize_personas(ctx) == {'created': 8}
    rows = get(ctx, 'personas')['results']
    assert len(rows) == 8
    for row in rows:
        assert row['data']['needs'] and row['data']['concerns']
        assert row['data']['budget_min'] is None and row['data']['budget_max'] is None
        assert row['data']['city'] == '' and row['data']['districts'] == []
        assert row['data']['move_in'] is None
    pet = next(row for row in rows if row['title'] == '需要养宠的租客')
    assert pet['data']['must_have'] == ['可养宠']
    p = prop(ctx)
    generated = task(ctx, property_ids=[p['id']], persona_id=pet['id'])
    frozen = AITask.objects.get(pk=generated['id']).snapshot
    assert frozen['persona']['id'] == pet['id']
    assert frozen['persona']['data']['concerns'] == pet['data']['concerns']


def test_builtin_persona_initialization_preserves_edits_archives_and_custom_records(ctx):
    custom = post(ctx, 'personas', {'title': '需要养宠的租客', 'data': {'needs': '我的自定义画像'}})
    initialize_personas(ctx)
    pet = next(row for row in get(ctx, 'personas')['results'] if row['title'] == custom['title'] and row['id'] != custom['id'])
    edited = patch(ctx, 'personas', pet, {'title': '本地养猫客群', 'archived': True, 'data': {'budget_max': 3500}})
    assert initialize_personas(ctx) == {'created': 0}
    assert initialize_personas(ctx) == {'created': 0}
    assert get(ctx, 'personas', archived='all')['count'] == 9
    assert get(ctx, 'personas')['count'] == 8
    assert get(ctx, f"personas/{pet['id']}") == edited
    assert get(ctx, f"personas/{custom['id']}")['data']['needs'] == '我的自定义画像'


def test_builtin_personas_remain_private_and_require_application_access(ctx):
    initialize_personas(ctx)
    own_ids = {row['id'] for row in get(ctx, 'personas')['results']}
    ctx['client'].force_authenticate(ctx['other'])
    assert initialize_personas(ctx) == {'created': 8}
    other_ids = {row['id'] for row in get(ctx, 'personas')['results']}
    assert own_ids.isdisjoint(other_ids)
    assert ctx['client'].get(f"{ctx['root']}/personas/{next(iter(own_ids))}").status_code == 404
    post(ctx, 'ai/tasks', {'kind': 'topics', 'request_key': 'foreign-persona', 'persona_id': next(iter(own_ids))}, 404)
    foreign_root = ctx['root'].replace(str(ctx['org'].pk), str(ctx['other'].owned_organizations.get().pk))
    assert ctx['client'].put(f'{foreign_root}/personas/built-ins', {}, format='json').status_code == 404
    ctx['app'].is_active = False; ctx['app'].save(update_fields=['is_active'])
    assert ctx['client'].put(f"{ctx['root']}/personas/built-ins", {}, format='json').status_code == 404
    assert Persona.objects.count() == 16


def published(ctx, monkeypatch, p):
    generated = execute(ctx, task(ctx, property_ids=[p['id']]), monkeypatch, copy_result(p['id']))
    return post(ctx, 'publications', dict(title='小红书作品', status='published', version_id=generated['result']['version_id'],
                                          data={'published_at': '2026-10-05T09:00:00+08:00'}))


def test_end_to_end_attribution_versions_deal_and_unique_viewings(ctx, monkeypatch):
    p = prop(ctx)
    persona = post(ctx, 'personas', dict(title='养猫的上班族', data={'must_have': ['可养宠']}))
    generated = execute(ctx, task(ctx, property_ids=[p['id']], persona_id=persona['id']), monkeypatch, copy_result(p['id']))
    c = get(ctx, f"contents/{generated['result']['content_id']}")
    v2 = post(ctx, f"contents/{c['id']}/versions", dict(revision=c['revision'], body=copy_result(p['id'])))
    assert v2['number'] == 2 and len(get(ctx, f"contents/{c['id']}/versions")) == 2
    publication = post(ctx, 'publications', dict(title='养猫租房', status='planned', version_id=v2['id'], data={'scheduled_date': '2026-10-05'}))
    assert get(ctx, 'overview/reports')['publications'] == []
    publication = patch(ctx, 'publications', publication, dict(status='published', data={'published_at': '2026-10-05T01:00:00Z'}))
    post(ctx, f"publications/{publication['id']}/metrics", {'views': 100, 'likes': 0})
    l = lead(ctx, budget_max=3000, city='上海', must_have=['可养宠'], source_id=publication['id'])
    assert get(ctx, f"leads/{l['id']}/matches")['matched'][0]['property']['id'] == p['id']
    for i in range(2):
        v = post(ctx, 'viewings', dict(title='看房', lead_id=l['id'], data={'scheduled_at': f'2026-10-0{6+i}T10:00:00+08:00', 'property_ids': [p['id']]}))
        patch(ctx, 'viewings', v, dict(status='done', data={'feedback': '认可户型'}))
    assert get(ctx, f"leads/{l['id']}")['status'] == 'new'
    patch(ctx, 'leads', l, dict(status='won', data={'deal_date': '2026-10-08', 'deal_property_id': p['id']}, mark_property_rented=True))
    result = get(ctx, 'overview/reports', start='2026-10-05', end='2026-10-05')
    assert result['summary'] == dict(leads=1, viewed=1, won=1, viewing_rate=1, deal_rate=1)
    assert result['publications'][0]['metrics'] == dict(views=100, likes=0, saves=None, comments=None)
    assert result['groups']['persona_id'][0]['key'] == persona['id']
    assert get(ctx, f"properties/{p['id']}")['status'] == 'rented'
    assert get(ctx, f"leads/{l['id']}/matches") == dict(matched=[], unknown=[], conflicts=[])
    old = get(ctx, f"contents/{c['id']}")
    assert old['changes'] and old['latest_version']['snapshot']['properties'][0]['status'] == 'available'
    assert get(ctx, 'overview/reports', start='2026-10-06')['summary']['deal_rate'] is None


def test_matching_unknown_conflict_and_no_automatic_relaxation(ctx):
    a = prop(ctx, pets='unknown', rent=None)
    b = prop(ctx, rent=3100)
    l = lead(ctx, city='上海', budget_max=3000, must_have=['可养宠'])
    matches = get(ctx, f"leads/{l['id']}/matches")
    assert not matches['matched'] and matches['unknown'][0]['property']['id'] == a['id']
    assert matches['conflicts'][0]['property']['id'] == b['id']
    patch(ctx, 'properties', b, dict(status='paused'))
    assert not get(ctx, f"leads/{l['id']}/matches")['conflicts']
    assert get(ctx, f"leads/{lead(ctx)['id']}/matches")['unknown']


def test_calendar_followup_next_date_and_timezone(ctx):
    p, l = prop(ctx), lead(ctx)
    follow = post(ctx, 'followups', dict(title='了解预算', lead_id=l['id'], data={'due_date': '2026-10-05'}))
    done = patch(ctx, 'followups', follow, dict(status='done', data={'next_due_date': '2026-10-07', 'next_step': '确认入住日期'}))
    patch(ctx, 'followups', done, dict(data={'summary': '补充摘要'}))
    assert len(get(ctx, 'followups')['results']) == 2
    post(ctx, 'viewings', dict(title='看房', lead_id=l['id'], data={'scheduled_at': '2026-10-05T17:00:00Z', 'property_ids': [p['id']]}))
    events = get(ctx, 'overview/calendar')['events']
    assert next(e for e in events if e['kind'] == 'viewings')['date'] == '2026-10-06'
    assert ctx['client'].put(f"{ctx['root']}/settings", {'timezone': 'Invalid/Zone'}, format='json').status_code == 400
    assert get(ctx, 'settings')['timezone'] == 'Asia/Shanghai'


def test_archive_revision_validation_and_duplicate_contacts(ctx):
    l = lead(ctx, contact='wx-test')
    duplicate = lead(ctx, contact='wx-test')
    assert duplicate['duplicates'] == [dict(id=l['id'], title=l['title'])]
    updated = patch(ctx, 'leads', l, dict(archived=True))
    patch(ctx, 'leads', l, dict(title='stale'), 409)
    assert get(ctx, 'leads')['count'] == 1 and get(ctx, 'leads', archived='all')['count'] == 2
    assert get(ctx, f"leads/{updated['id']}")['data']['contact'] == 'wx-test'
    post(ctx, 'leads', dict(title='预算不符', data={'consulted_on': '2026-10-05', 'budget_min': 4000, 'budget_max': 3000}), 400)
    post(ctx, 'properties', dict(title='越权', owner=ctx['other'].pk), 400)


@pytest.mark.parametrize('resource', ['properties', 'personas', 'leads', 'contents'])
def test_private_owner_and_org_boundaries(ctx, resource):
    data = {'consulted_on': '2026-10-05'} if resource == 'leads' else {}
    record = post(ctx, resource, dict(title='私有', data=data))
    ctx['client'].force_authenticate(ctx['other'])
    assert get(ctx, resource)['count'] == 0
    assert ctx['client'].get(f"{ctx['root']}/{resource}/{record['id']}").status_code == 404
    assert ctx['client'].patch(f"{ctx['root']}/{resource}/{record['id']}", {'revision': 0, 'title': '偷改'}, format='json').status_code == 404
    other_root = ctx['root'].replace(str(ctx['org'].pk), str(ctx['other'].owned_organizations.get().pk))
    assert ctx['client'].get(f'{other_root}/{resource}').status_code == 404
    ctx['client'].force_authenticate(None)
    assert ctx['client'].get(f"{ctx['root']}/{resource}").status_code in (401, 403)


def test_cross_owner_reference_task_and_version_access(ctx, monkeypatch):
    p = prop(ctx); publication = published(ctx, monkeypatch, p)
    ctx['client'].force_authenticate(ctx['other'])
    post(ctx, 'leads', dict(title='越权来源', data={'consulted_on': '2026-10-05', 'source_id': publication['id']}), 404)
    post(ctx, 'ai/tasks', dict(kind='copy', request_key='x', property_ids=[p['id']]), 404)
    assert ctx['client'].get(f"{ctx['root']}/versions/{publication['version_id']}/download").status_code == 404
    ctx['client'].force_authenticate(ctx['user'])
    ctx['app'].is_active = False; ctx['app'].save()
    assert ctx['client'].get(f"{ctx['root']}/properties").status_code == 404


def test_publication_stale_snapshot_and_immutable_published_version(ctx, monkeypatch):
    p = prop(ctx)
    generated = execute(ctx, task(ctx, property_ids=[p['id']]), monkeypatch, copy_result(p['id']))
    publication = post(ctx, 'publications', dict(title='待发', status='planned', version_id=generated['result']['version_id'], data={'scheduled_date': '2026-10-05'}))
    patch(ctx, 'properties', p, dict(data={'rent': 3000}))
    assert get(ctx, 'overview/calendar')['events'][0]['actionable'] is False
    patch(ctx, 'publications', publication, dict(status='published', data={'published_at': '2026-10-05T10:00:00+08:00'}), 400)
    c = get(ctx, f"contents/{generated['result']['content_id']}")
    body = copy_result(p['id']); body['body'] = '月租3000元，临街有噪声。'
    v = post(ctx, f"contents/{c['id']}/versions", dict(revision=c['revision'], body=body))
    pub = patch(ctx, 'publications', publication, dict(version_id=v['id'], status='published', data={'published_at': '2026-10-05T10:00:00+08:00'}))
    patch(ctx, 'publications', pub, dict(version_id=generated['result']['version_id']), 400)
    assert get(ctx, f"contents/{c['id']}/versions")[1]['body']['body'].startswith('月租2800')


def test_task_idempotency_failure_recovery_and_cancel(ctx, monkeypatch):
    values = dict(kind='copy', content_type='qa', request_key='request-1', instruction='问答')
    one = post(ctx, 'ai/tasks', values, 202)
    assert post(ctx, 'ai/tasks', values, 200)['id'] == one['id']
    post(ctx, 'ai/tasks', {**values, 'instruction': 'changed'}, 409)
    with pytest.raises(RuntimeError): execute(ctx, one, monkeypatch, {'titles': []})
    assert get(ctx, f"ai/tasks/{one['id']}")['status'] == 'failed'
    second = task(ctx, content_type='qa')
    monkeypatch.setattr(ai, 'submit_run_command', lambda **kw: None)
    assert post(ctx, f"ai/tasks/{second['id']}/cancel", {}, 200)['status'] == 'cancelled'
    result = execute(ctx, second, monkeypatch, copy_result())
    assert result['status'] == 'cancelled' and Content.objects.count() == 0
    third = task(ctx, content_type='qa')
    assert execute(ctx, third, monkeypatch, copy_result())['status'] == 'succeeded'


def test_during_generation_cancellation_and_permissions(ctx, monkeypatch):
    t = task(ctx, content_type='qa')
    model = AITask.objects.get(pk=t['id'])
    def cancel(*args):
        AITask.objects.filter(pk=model.pk).update(cancel_requested=True, status='cancelled')
        return copy_result()
    monkeypatch.setattr(runtime, 'call_model', cancel)
    runtime.execute(dict(run_id=str(model.run_id), organization_id=str(ctx['org'].pk), input={'task_id': str(model.pk)}), Sink())
    assert Content.objects.count() == 0
    model.refresh_from_db(); assert model.result == {} and model.status == 'cancelled'


def test_topics_apply_once_and_generating_plan_item_keeps_same_content(ctx, monkeypatch):
    p = prop(ctx)
    t = task(ctx, 'topics', property_ids=[p['id']], start_date='2026-10-05')
    result = {'topics': [dict(title=f'选题 {i}', angle='真实费用', content_type='property', property_ids=[p['id']]) for i in range(7)]}
    execute(ctx, t, monkeypatch, result)
    applied = post(ctx, f"ai/tasks/{t['id']}/apply", {}, 200)
    post(ctx, f"ai/tasks/{t['id']}/apply", {}, 200)
    assert Content.objects.count() == 7
    c = get(ctx, f"contents/{applied['result']['content_ids'][0]}")
    copy = execute(ctx, task(ctx, property_ids=[p['id']], content_id=c['id']), monkeypatch, copy_result(p['id']))
    assert copy['result']['content_id'] == c['id']
    execute(ctx, task(ctx, property_ids=[p['id']], content_id=c['id']), monkeypatch, copy_result(p['id']))
    assert len(get(ctx, f"contents/{c['id']}/versions")) == 2
    assert len(get(ctx, 'overview/calendar')['events']) == 7


def test_extract_requires_review_and_unknown_fields_do_not_erase(ctx, monkeypatch):
    l = lead(ctx, budget_max=3000, contact='private-phone')
    t = task(ctx, 'extract', lead_id=l['id'], instruction='我需要养猫')
    model = AITask.objects.get(pk=t['id'])
    assert 'private-phone' not in json.dumps(model.snapshot)
    result = execute(ctx, t, monkeypatch, {'requirements': {'must_have': ['可养宠'], 'city': ''}})
    assert result['result'] == {'requirements': {'must_have': ['可养宠']}}
    assert get(ctx, f"leads/{l['id']}")['data']['must_have'] == []
    saved = patch(ctx, 'leads', l, dict(data=result['result']['requirements']))
    assert saved['data']['budget_max'] == 3000 and saved['data']['must_have'] == ['可养宠']


@pytest.mark.parametrize('change', [{'rent': None}, {'district': ''}, {'layout': ''}])
def test_incomplete_property_cannot_generate(ctx, change):
    p = prop(ctx, **change)
    post(ctx, 'ai/tasks', dict(kind='copy', request_key=str(uuid4()), property_ids=[p['id']]), 400)


def test_photos_and_review_citations_validated(ctx, monkeypatch):
    p = prop(ctx)
    t = task(ctx, property_ids=[p['id']])
    invalid = copy_result(str(uuid4()))
    with pytest.raises(RuntimeError): execute(ctx, t, monkeypatch, invalid)
    assert ContentVersion.objects.count() == 0
    t = task(ctx, 'review')
    with pytest.raises(RuntimeError): execute(ctx, t, monkeypatch, {'answer': '分析', 'publication_ids': [str(uuid4())]})
    assert get(ctx, 'overview/reports')['summary']['viewing_rate'] is None


def test_archiving_publication_does_not_reschedule_original_topic(ctx, monkeypatch):
    p = prop(ctx)
    topic = post(ctx, 'contents', dict(title='待创作选题', data={'planned_date': '2026-10-05', 'property_ids': [p['id']]}))
    generated = execute(ctx, task(ctx, property_ids=[p['id']], content_id=topic['id']), monkeypatch, copy_result(p['id']))
    pub = post(ctx, 'publications', dict(title='发布作品', version_id=generated['result']['version_id'],
        status='published', data={'scheduled_date': '2026-10-05', 'published_at': '2026-10-05T01:00:00Z'}))
    patch(ctx, 'publications', pub, dict(archived=True))
    assert get(ctx, 'overview/calendar')['events'] == []


def test_public_copy_snapshot_excludes_unrelated_customer_private_data(ctx, monkeypatch):
    p = prop(ctx)
    l = lead(ctx, contact='confidential-contact', notes='confidential-notes')
    t = task(ctx, property_ids=[p['id']], lead_id=l['id'])
    model = AITask.objects.select_related('organization', 'owner').get(pk=t['id'])
    called = {}
    def generate(**kwargs):
        called.update(kwargs)
        return copy_result(p['id'])
    monkeypatch.setattr(runtime, 'generate_json', generate)
    runtime.call_model(model, lambda: False)
    assert called['resource_type'] == 'rental_generation'
    assert called['organization'] == ctx['org'] and called['user'] == ctx['user']
    assert 'confidential-contact' not in called['content'] and 'confidential-notes' not in called['content']


def test_runtime_streams_incremental_output_before_saving_and_filters_internal_events(ctx, monkeypatch):
    t = task(ctx, content_type='qa')
    model = AITask.objects.get(pk=t['id'])
    class RecordingSink(Sink):
        events = []
        def emit(self, kind, payload): self.events.append((kind, payload))
    sink = RecordingSink()
    def model_call(task, cancelled, on_event):
        on_event('output.delta', {'text': '{"body":"正在生成'})
        assert sink.events[-1] == ('output.delta', {'text': '{"body":"正在生成'})
        assert Content.objects.count() == 0  # the message is visible before completion
        on_event('agent.item', {'type': 'reasoning', 'text': 'internal-reasoning'})
        on_event('tool.started', {'input': 'private-tool-arguments'})
        on_event('progress.updated', {'message': 'private-provider-diagnostic'})
        on_event('output.snapshot', {'text': '{"body":"修正后的文案"}'})
        return copy_result()
    monkeypatch.setattr(runtime, 'call_model', model_call)
    runtime.execute(dict(run_id=str(model.run_id), organization_id=str(ctx['org'].pk), input={'task_id': str(model.pk)}), sink)
    serialized = json.dumps(sink.events, ensure_ascii=False)
    assert 'internal-reasoning' not in serialized and 'private-tool-arguments' not in serialized
    assert 'private-provider-diagnostic' not in serialized
    stages = [payload['stage'] for kind, payload in sink.events if kind == 'progress.updated']
    assert stages == ['已读取资料，正在生成内容', '正在校验文案与资料引用', '生成完成，结果已保存']
    assert sink.events[-2][0] == 'progress.updated' and Content.objects.count() == 1
    fetched = get(ctx, f"ai/tasks/{t['id']}")
    assert fetched['run_id'] == str(model.run_id) and fetched['organization_id'] == str(ctx['org'].pk)


def test_stream_drops_late_output_after_cancel(ctx, monkeypatch):
    t = task(ctx, content_type='qa'); model = AITask.objects.get(pk=t['id'])
    events = []
    class RecordingSink(Sink):
        def emit(self, kind, payload): events.append((kind, payload))
    def model_call(task, cancelled, on_event):
        on_event('output.delta', {'text': '已收到的内容'})
        AITask.objects.filter(pk=model.pk).update(cancel_requested=True, status='cancelled')
        on_event('output.delta', {'text': '迟到的输出'})
        return copy_result()
    monkeypatch.setattr(runtime, 'call_model', model_call)
    runtime.execute(dict(run_id=str(model.run_id), organization_id=str(ctx['org'].pk), input={'task_id': str(model.pk)}), RecordingSink())
    assert [payload['text'] for kind, payload in events if kind.startswith('output.')] == ['已收到的内容']
    assert not Content.objects.exists()


def test_run_message_endpoints_remain_owner_only_including_organization_admin(ctx):
    from modules.execution.models import RunEvent
    t = task(ctx, content_type='qa'); model = AITask.objects.get(pk=t['id'])
    RunEvent.objects.create(organization=ctx['org'], run=model.run, sequence=1, type='output.delta', payload={'text': 'private-copy'})
    root = f"/api/v1/organizations/{ctx['org'].pk}/runs/{model.run_id}"
    assert ctx['client'].get(root + '/events').status_code == 200
    assert ctx['client'].get(root + '/stream', HTTP_ACCEPT='text/event-stream').status_code == 200
    Membership.objects.filter(organization=ctx['org'], user=ctx['other']).update(role=Membership.Role.ADMIN)
    ctx['client'].force_authenticate(ctx['other'])
    for suffix in ['', '/events', '/stream', '/snapshot']:
        assert ctx['client'].get(root + suffix).status_code == 404
    ctx['client'].force_authenticate(ctx['user'])
    ctx['app'].is_active = False; ctx['app'].save()
    assert ctx['client'].get(root + '/events').status_code == 404


def test_existing_stream_rechecks_application_access_on_each_batch(ctx):
    from asgiref.sync import async_to_sync
    from modules.execution.api.streaming import _load_event_batch, StreamAccessLost
    t = task(ctx, content_type='qa'); model = AITask.objects.get(pk=t['id'])
    kwargs = dict(user=ctx['user'], organization_id=ctx['org'].pk, run_id=model.run_id, after=0, limit=100)
    assert async_to_sync(_load_event_batch)(**kwargs) == []
    ctx['app'].is_active = False; ctx['app'].save()
    with pytest.raises(StreamAccessLost): async_to_sync(_load_event_batch)(**kwargs)

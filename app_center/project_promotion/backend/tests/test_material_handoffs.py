import json
from uuid import uuid4

import pytest
from apps.conversations.models import Conversation
from apps.enterprise.models import Membership
from ..models import Handoff, Topic, Channel, Version, Case
from .test_promotion import ctx, case, post, get, patch
from .test_topic_handoffs import target_app


def test_material_handoff_preserves_scope_edits_and_conversation(ctx):
    target = target_app(ctx, 'topic-explorer')
    sources = [case(ctx), case(ctx)]
    payload = dict(case_ids=[r['id'] for r in sources], platform='wechat', direction='演示流程',
        audience='独立创作者', requirements='不讲大而全的平台介绍')
    h = post(ctx, 'handoffs', payload)
    assert h['source_type'] == 'materials' and h['topic_id'] is h['version_id'] is None
    assert h['kind'] == 'topic-explorer'
    assert set(h['draft']) == {'source', 'platform', 'content_type', 'goal', 'direction', 'audience', 'requirements'}
    assert h['draft']['goal'] == h['draft']['content_type'] == ''
    for key in ('platform', 'direction', 'audience', 'requirements'):
        assert h['draft'][key] == payload[key]
    material = json.loads(h['draft']['source'])['cases'][0]
    assert material['data']['assets'][0]['url'] == 'https://example.com/guide'
    assert 'source=' not in h['url'] and '/chat?slug=topic-explorer' in h['url']
    conversation = Conversation.objects.create(organization=ctx['org'], user=ctx['user'],
        chat_application=target.chat_application, title='选题探索')
    edited = ctx['client'].patch(f'{ctx["root"]}/handoffs/{h["id"]}', dict(revision=h['revision'],
        draft={'goal': 'trust', 'content_type': 'demo', 'platform': '', 'audience': '修改后的读者'},
        conversation_id=str(conversation.pk)), format='json')
    assert edited.status_code == 200
    reopened = post(ctx, 'handoffs', {**payload, 'case_ids': list(reversed(payload['case_ids']))}, 200)
    assert reopened['id'] == h['id']
    assert reopened['draft']['platform'] == ''
    assert reopened['draft']['goal'] == 'trust'
    assert reopened['draft']['content_type'] == 'demo'
    assert reopened['draft']['audience'] == '修改后的读者'
    assert f'conversation={conversation.pk}' in reopened['url']
    assert get(ctx, f'handoffs/{h["id"]}')['draft'] == reopened['draft']
    assert get(ctx, 'handoffs')[0]['id'] == h['id']
    assert post(ctx, 'handoffs', {**payload, 'requirements': '新要求'})['id'] != h['id']
    patch(ctx, 'cases', sources[0], {'data': {'conditions': '增加条件'}})
    assert post(ctx, 'handoffs', payload)['id'] != h['id']
    assert Topic.objects.count() == Channel.objects.count() == Version.objects.count() == 0
    post(ctx, f'handoffs/{h["id"]}/results', {}, 400)


def test_blank_scope_does_not_infer_audience_from_materials(ctx):
    target_app(ctx, 'topic-explorer')
    h = post(ctx, 'handoffs', {'case_ids': [case(ctx)['id']]})
    assert all(value == '' for key, value in h['draft'].items() if key != 'source')


@pytest.mark.parametrize('unavailable', ['missing', 'inactive', 'private', 'other_org'])
def test_material_target_availability(ctx, unavailable):
    source = case(ctx)
    if unavailable != 'missing':
        target = target_app(ctx, 'topic-explorer')
        if unavailable == 'inactive':
            target.is_active = False
        elif unavailable == 'private':
            target.visibility = 'private'
            target.created_by = ctx['other']
            Membership.objects.filter(organization=ctx['org'], user=ctx['user']).update(role=Membership.Role.VIEWER)
        else:
            target.organization = ctx['other'].owned_organizations.get()
        target.save()
    assert '选题探索' in str(post(ctx, 'handoffs', {'case_ids': [source['id']]}, 400))
    assert Handoff.objects.count() == 0


def test_material_access_status_and_handoff_isolation(ctx):
    target_app(ctx, 'topic-explorer')
    source = case(ctx)
    payload = {'case_ids': [source['id']]}
    ctx['client'].force_authenticate(ctx['other'])
    post(ctx, 'handoffs', payload, 404)
    ctx['client'].force_authenticate(ctx['user'])
    source = patch(ctx, 'cases', source, {'status': 'draft'})
    post(ctx, 'handoffs', payload, 400)
    source = patch(ctx, 'cases', source, {'status': 'confirmed', 'archived': True})
    post(ctx, 'handoffs', payload, 400)
    source = patch(ctx, 'cases', source, {'archived': False})
    h = post(ctx, 'handoffs', payload)
    ctx['client'].force_authenticate(ctx['other'])
    for method in ('get', 'patch'):
        assert getattr(ctx['client'], method)(f'{ctx["root"]}/handoffs/{h["id"]}').status_code == 404
    ctx['client'].force_authenticate(ctx['user'])
    Case.objects.filter(pk=source['id']).update(organization=ctx['other'].owned_organizations.get())
    post(ctx, 'handoffs', payload, 404)


@pytest.mark.parametrize('extra', [{'case_ids': []}, {'case_ids': ['invalid']}, {'case_ids': [str(uuid4())] * 21},
    {'platform': 'invalid'}, {'content_type': 'invalid'}, {'goal': 'invalid'}, {'topic_id': str(uuid4())},
    {'target_id': 1}, {'direction': 'x' * 2001}, {'requirements': 'x' * 30001}])
def test_material_handoff_validates_inputs(ctx, extra):
    target_app(ctx, 'topic-explorer')
    post(ctx, 'handoffs', {'case_ids': [case(ctx)['id']], **extra}, 400)
    assert Handoff.objects.count() == 0


def test_material_handoff_rejects_oversized_context(ctx):
    target_app(ctx, 'topic-explorer')
    source = case(ctx)
    Case.objects.filter(pk=source['id']).update(data={'facts': 'x' * 75001})
    post(ctx, 'handoffs', {'case_ids': [source['id']]}, 400)
    assert Handoff.objects.count() == 0

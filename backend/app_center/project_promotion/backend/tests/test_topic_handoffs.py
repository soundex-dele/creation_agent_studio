import json
import pytest
from apps.applications.models import Application, ChatApplication
from apps.conversations.models import Conversation
from apps.enterprise.models import Membership
from ..models import Channel, Handoff, Version
from .test_promotion import ctx, case, topic, post, get, patch


def target_app(ctx, slug):
    target = Application.objects.create(organization=ctx['org'], category=ctx['app'].category,
        name=slug, slug=slug, created_by=ctx['user'], kind='chat', visibility='organization')
    ChatApplication.objects.create(application=target)
    return target


@pytest.mark.parametrize('platform,slug,task,form_platform', [
    ('wechat', 'wechat-viral-article', 'full-article', None),
    ('xiaohongshu', 'write-image-text-copy', 'full', 'xiaohongshu'),
    ('douyin', 'write-short-video-copy', 'storyboard', 'douyin'),
    ('moments', 'write-image-text-copy', 'photo-caption', 'general'),
])
def test_topic_opens_matching_app_without_a_copy_version(ctx, platform, slug, task, form_platform):
    target = target_app(ctx, slug)
    source = case(ctx)
    second = case(ctx)
    idea = post(ctx, 'topics', dict(title='完整流程介绍', status='confirmed', case_ids=[source['id'], second['id']],
        data=dict(audience='创作者', thesis='连贯工作流', outline='从输入到发布')))
    payload = dict(topic_id=idea['id'], platform=platform)
    h = post(ctx, 'handoffs', payload)
    assert h['version_id'] is None
    assert h['kind'] == slug
    assert h['url'].startswith(f'/applications/{target.pk}/chat?slug={slug}&')
    assert f'promotionApplication={ctx["app"].pk}&promotionHandoff={h["id"]}' in h['url']
    assert h['draft']['task'] == task
    assert h['draft'].get('platform') == form_platform
    assert h['draft']['audience'] == '创作者'
    if platform == 'moments':
        assert '朋友圈' in h['draft']['requirements']
    context = json.loads(h['draft']['source'])
    assert context['topic']['data']['thesis'] == '连贯工作流'
    assert context['topic']['data']['outline'] == '从输入到发布'
    assert {row['id'] for row in context['cases']} == {source['id'], second['id']}
    assert 'case' not in context
    assert h['platform'] == platform
    assert h['topic_id'] == idea['id']
    assert Channel.objects.count() == 0
    assert Version.objects.count() == 0
    assert get(ctx, f'handoffs/{h["id"]}')['id'] == h['id']
    changed = ctx['client'].patch(f'{ctx["root"]}/handoffs/{h["id"]}',
        dict(revision=h['revision'], draft={'source': '用户修改后的素材', 'audience': '新的读者'}), format='json')
    assert changed.status_code == 200
    reopened = post(ctx, 'handoffs', payload, 200)
    assert reopened['id'] == h['id']
    assert reopened['draft']['source'] == '用户修改后的素材'
    assert reopened['draft']['audience'] == '新的读者'
    assert Handoff.objects.count() == 1
    assert Channel.objects.count() == 0


def test_topic_handoff_resumes_conversation_and_snapshots_changed_sources(ctx):
    target = target_app(ctx, 'wechat-viral-article')
    source = case(ctx)
    idea = topic(ctx, source)
    payload = dict(topic_id=idea['id'], platform='wechat')
    h = post(ctx, 'handoffs', payload)
    conversation = Conversation.objects.create(organization=ctx['org'], user=ctx['user'],
        chat_application=target.chat_application, title='选题创作')
    attached = ctx['client'].patch(f'{ctx["root"]}/handoffs/{h["id"]}',
        dict(revision=h['revision'], conversation_id=str(conversation.pk)), format='json')
    assert attached.status_code == 200, attached.data
    reopened = post(ctx, 'handoffs', payload, 200)
    assert reopened['id'] == h['id']
    assert f'conversation={conversation.pk}' in reopened['url']
    patch(ctx, 'cases', source, dict(data={'conditions': '补充条件'}))
    fresh = post(ctx, 'handoffs', payload)
    assert fresh['id'] != h['id']
    assert 'conversation=' not in fresh['url']
    assert Handoff.objects.get(pk=h['id']).snapshot['cases'][0]['revision'] == 0
    assert Channel.objects.count() == Version.objects.count() == 0


@pytest.mark.parametrize('unavailable', ['missing', 'inactive', 'private', 'other_org'])
def test_unavailable_target_does_not_create_partial_records(ctx, unavailable):
    idea = topic(ctx, case(ctx))
    if unavailable != 'missing':
        target = target_app(ctx, 'wechat-viral-article')
        if unavailable == 'inactive':
            target.is_active = False
        elif unavailable == 'private':
            target.visibility = 'private'
            target.created_by = ctx['other']
            Membership.objects.filter(organization=ctx['org'], user=ctx['user']).update(role=Membership.Role.VIEWER)
        else:
            target.organization = ctx['other'].owned_organizations.get()
        target.save()
    response = post(ctx, 'handoffs', dict(topic_id=idea['id'], platform='wechat'), 400)
    assert '公众号爆款写作' in str(response)
    assert Channel.objects.count() == Handoff.objects.count() == Version.objects.count() == 0


def test_topic_handoffs_enforce_source_access_and_confirmation(ctx):
    target_app(ctx, 'wechat-viral-article')
    source = case(ctx)
    idea = topic(ctx, source)
    payload = dict(topic_id=idea['id'], platform='wechat')
    ctx['client'].force_authenticate(ctx['other'])
    post(ctx, 'handoffs', payload, 404)
    ctx['client'].force_authenticate(ctx['user'])
    idea = patch(ctx, 'topics', idea, dict(status='draft'))
    post(ctx, 'handoffs', payload, 400)
    idea = patch(ctx, 'topics', idea, dict(status='confirmed', archived=True))
    post(ctx, 'handoffs', payload, 400)
    patch(ctx, 'topics', idea, dict(archived=False))
    source = patch(ctx, 'cases', source, dict(status='draft'))
    post(ctx, 'handoffs', payload, 400)
    patch(ctx, 'cases', source, dict(status='confirmed'))
    assert Channel.objects.count() == Handoff.objects.count() == 0
    h = post(ctx, 'handoffs', payload)
    ctx['client'].force_authenticate(ctx['other'])
    assert ctx['client'].get(f'{ctx["root"]}/handoffs/{h["id"]}').status_code == 404
    assert ctx['client'].get(f'{ctx["root"]}/handoffs/{h["id"]}/results').status_code == 404

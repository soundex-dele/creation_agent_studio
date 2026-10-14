from copy import deepcopy
from uuid import uuid4
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from modules.execution.models import Run
from app_center.project_promotion import runtime
from .. import ai
from ..models import AITask, Case, Topic, Channel, Version, Handoff
from ..access import can_access_run


@pytest.fixture
def ctx(db, monkeypatch):
    owner = get_user_model().objects.create_user(username='promotion-owner')
    other = get_user_model().objects.create_user(username='promotion-other')
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role=Membership.Role.ADMIN)
    cat = ApplicationCategory.objects.create(name='Promotion tests', slug='promotion-tests')
    app = Application.objects.create(organization=org, category=cat, name='项目宣传助手', slug='project-promotion', created_by=owner, kind='custom', visibility='organization')
    client = APIClient()
    client.force_authenticate(owner)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.pk))
    def start(**kwargs):
        return Run.objects.create(organization=org, owner=kwargs['actor'], source_type='application', source_id=str(app.pk),
            executor_kind='media', executor_key='project-promotion', input=kwargs['input_data']), False
    monkeypatch.setattr(ai, 'start_application_run', start)
    return dict(client=client, app=app, org=org, user=owner, other=other,
        root=f'/api/v1/organizations/{org.pk}/applications/{app.pk}/project-promotion')


def post(c, path, value, status=201):
    r = c['client'].post(f"{c['root']}/{path}", value, format='json')
    assert r.status_code == status, r.data
    return r.data


def get(c, path):
    r = c['client'].get(f"{c['root']}/{path}")
    assert r.status_code == 200, getattr(r, 'data', None)
    return r.data


def patch(c, kind, row, value, status=200):
    r = c['client'].patch(f"{c['root']}/{kind}/{row['id']}", {'revision': row['revision'], **value}, format='json')
    assert r.status_code == status, r.data
    return r.data


def case(c):
    return post(c, 'cases', dict(title='公众号排版演示', status='confirmed', data=dict(audience='创作者', problem='排版耗时',
        solution='主题排版', implemented='生成 HTML', evidence='手动验证的 HTML 输出', conditions='需安装 Skill', extensions='未来批量排版',
        assets=[dict(label='说明', kind='document', url='https://example.com/guide', note='演示资料')])) )


def topic(c, source):
    return post(c, 'topics', dict(title='从文章到排版', status='confirmed', case_id=source['id'], data=dict(angle='现场演示', audience='创作者', direction='demo')))


def channel(c, source, platform='wechat'):
    return post(c, 'channels', dict(title=source['title'], topic_id=source['id'], platform=platform))


def version(c, row, text='基于真实功能的文案'):
    return post(c, f"channels/{row['id']}/versions", dict(revision=row['revision'], body=dict(title='真实演示', body=text)))


def publish(c, row):
    v = version(c, row)
    row = get(c, f"channels/{row['id']}")
    row = post(c, f"channels/{row['id']}/versions/{v['id']}/confirm", dict(revision=row['revision']), 200)
    return patch(c, 'channels', row, dict(status='published', data=dict(published_at='2026-10-14T12:00:00+08:00', publication_url='https://example.com/post')))


class Sink:
    cancelled = False
    def emit(self, *args):
        pass


def execute(c, task, monkeypatch, result):
    captured = {}
    def generate(**kwargs):
        captured.update(kwargs)
        return deepcopy(result)
    monkeypatch.setattr(runtime, 'generate_json', generate)
    runtime.execute(dict(run_id=task['run_id'], organization_id=str(c['org'].pk), input={'task_id': task['id']}), Sink())
    return captured


def test_full_four_channel_workflow(ctx):
    source = case(ctx)
    idea = topic(ctx, source)
    channels = [channel(ctx, idea, p) for p in ['wechat', 'xiaohongshu', 'douyin', 'moments']]
    first = publish(ctx, channels[0])
    assert all(get(ctx, f"channels/{r['id']}")['status'] == 'draft' for r in channels[1:])
    original = first['confirmed_version_id']
    version(ctx, first, '新版草稿')
    first = get(ctx, f"channels/{first['id']}")
    assert first['confirmed_version_id'] == original
    assert first['latest_version']['number'] == 2
    assert first['status'] == 'published'
    assert len(get(ctx, f"channels/{first['id']}/versions")) == 2
    post(ctx, 'feedback', dict(title='首次观察', channel_id=first['id'], data=dict(observed_on='2026-10-14', views=100, inquiries=2, questions='可以接入资料吗？')))
    post(ctx, 'feedback', dict(title='再次观察', channel_id=first['id'], data=dict(observed_on='2026-10-15', views=150, inquiries=3)))
    post(ctx, 'feedback', dict(title='来源不明', data=dict(observed_on='2026-10-15', inquiries=8, questions='能定制吗？')))
    stats = get(ctx, 'report')
    assert stats['groups']['platforms'][0]['metrics']['views'] == dict(total=150, samples=1)
    assert stats['groups']['cases'][0]['metrics']['inquiries']['total'] == 3
    assert stats['groups']['platforms'][0]['metrics']['interactions'] == dict(total=None, samples=0)
    assert stats['unknown_source_count'] == 1
    r = ctx['client'].get(f"{ctx['root']}/channels/{first['id']}/versions/{original}/download")
    assert r.status_code == 200 and '真实' in r.content.decode()


def test_confirmation_and_conflicts(ctx):
    post(ctx, 'cases', dict(title='空白', status='confirmed'), 400)
    source = case(ctx); idea = topic(ctx, source); row = channel(ctx, idea)
    post(ctx, 'channels', dict(title='重复', topic_id=idea['id'], platform='wechat'), 409)
    patch(ctx, 'channels', row, dict(status='published'), 400)
    v = version(ctx, row)
    patch(ctx, 'channels', row, dict(title='过时编辑'), 409)
    patch(ctx, 'cases', source, dict(data={'evidence': '新证据'}))
    row = get(ctx, f"channels/{row['id']}")
    post(ctx, f"channels/{row['id']}/versions/{v['id']}/confirm", dict(revision=row['revision']), 409)
    post(ctx, 'feedback', dict(title='尚未发布', channel_id=row['id'], data={'observed_on': '2026-10-14'}), 400)
    post(ctx, 'cases', dict(title='危险链接', data={'assets': [dict(label='链接', url='javascript:alert(1)')]}), 400)


def test_private_records_and_run_tree(ctx):
    source = case(ctx)
    task = post(ctx, 'ai/tasks', dict(kind='topics', case_id=source['id'], request_key='private'), 202)
    run = Run.objects.get(pk=task['run_id'])
    assert can_access_run(ctx['user'], run)
    assert not can_access_run(ctx['other'], run)
    ctx['client'].force_authenticate(ctx['other'])
    assert get(ctx, 'cases')['results'] == []
    assert get(ctx, 'ai/tasks')['results'] == []
    for path in [f"cases/{source['id']}", f"ai/tasks/{task['id']}"]:
        assert ctx['client'].get(f"{ctx['root']}/{path}").status_code == 404
    post(ctx, 'topics', dict(title='越权引用', case_id=source['id']), 404)
    r = ctx['client'].get(f"/api/v1/organizations/{ctx['org'].pk}/runs/{run.pk}")
    assert r.status_code in (403, 404)
    ctx['client'].force_authenticate(ctx['user'])
    ctx['app'].is_active = False; ctx['app'].save()
    assert not can_access_run(ctx['user'], run)


def test_generation_idempotency_snapshot_and_apply(ctx, monkeypatch):
    source = case(ctx); idea = topic(ctx, source); row = channel(ctx, idea)
    data = dict(kind='copy', channel_id=row['id'], request_key='stable')
    task = post(ctx, 'ai/tasks', data, 202)
    assert post(ctx, 'ai/tasks', data, 200)['id'] == task['id']
    post(ctx, 'ai/tasks', {**data, 'instruction': '改动'}, 409)
    patch(ctx, 'cases', source, {'data': {'extensions': '另一设想'}})
    captured = execute(ctx, task, monkeypatch, dict(title='演示', body='真实正文', materials='说明链接'))
    assert '未来批量排版' in captured['content']
    assert '不能虚构' in captured['instruction']
    assert Version.objects.count() == 0
    applied = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    assert applied['applied'] is True
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    assert Version.objects.count() == 1
    assert get(ctx, f"channels/{row['id']}")['confirmed_version_id'] is None
    new_task = post(ctx, 'ai/tasks', {**data, 'request_key': 'new'}, 202)
    assert new_task['id'] != task['id']


def test_generation_failure_preserves_confirmed_version(ctx, monkeypatch):
    source = case(ctx); idea = topic(ctx, source); row = publish(ctx, channel(ctx, idea))
    task = post(ctx, 'ai/tasks', dict(kind='copy', channel_id=row['id'], request_key='failure'), 202)
    monkeypatch.setattr(runtime, 'generate_json', lambda **kwargs: {'bad': 'shape'})
    with pytest.raises(RuntimeError):
        runtime.execute(dict(run_id=task['run_id'], organization_id=str(ctx['org'].pk), input={'task_id': task['id']}), Sink())
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'failed'
    assert get(ctx, f"channels/{row['id']}")['confirmed_version_id'] == row['confirmed_version_id']
    post(ctx, f"ai/tasks/{task['id']}/apply", {}, 404)
    post(ctx, 'ai/tasks', dict(kind='copy', channel_id=row['id'], request_key='retry'), 202)


def test_case_extraction_and_review_are_editable_drafts(ctx, monkeypatch):
    task = post(ctx, 'ai/tasks', dict(kind='case', instruction='生成 HTML 的开发记录', request_key='extract'), 202)
    execute(ctx, task, monkeypatch, dict(title='提取案例', data={'case_type': 'customer', 'implemented': '生成 HTML'}))
    result = post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    source = get(ctx, f"cases/{result['result']['case_id']}")
    assert source['status'] == 'draft' and source['data']['case_type'] == 'demo'
    source = case(ctx)
    assert get(ctx, 'report')['groups'] == dict(platforms=[], cases=[])
    feedback = post(ctx, 'feedback', dict(title='匿名问题', data=dict(observed_on='2026-10-14', questions='可以接入资料吗？')))
    review = post(ctx, 'ai/tasks', dict(kind='review', case_id=source['id'], request_key='review'), 202)
    execute(ctx, review, monkeypatch, dict(analysis='暂无效果数据，依据匿名问题策划', topics=[dict(title='接入资料演示', data=dict(angle='展示条件', source_feedback_id=feedback['id']))]))
    result = post(ctx, f"ai/tasks/{review['id']}/apply", {}, 200)
    t = get(ctx, f"topics/{result['result']['topic_ids'][0]}")
    assert t['status'] == 'draft' and t['data']['source_feedback_id'] == feedback['id']


def test_brand_snapshot_uses_private_selected_products(ctx):
    from app_center.brand_library.backend.models import BrandProfile, BrandProduct
    brand_app = Application.objects.create(organization=ctx['org'], category=ctx['app'].category, name='品牌', slug='brand-library', created_by=ctx['user'], kind='custom', visibility='organization')
    ownership = dict(organization=ctx['org'], application=brand_app, owner=ctx['user'])
    profile = BrandProfile.objects.create(**ownership, name='工坊', positioning={'audience': '创作者'}, voice={'keywords': '朴实'})
    product = BrandProduct.objects.create(**ownership, profile=profile, name='Agent Studio', facts=['支持排版'])
    source = case(ctx)
    reference = dict(profile_id=str(profile.pk), modules=['positioning', 'voice', 'products'], product_ids=[str(product.pk)], example_ids=[])
    task = post(ctx, 'ai/tasks', dict(kind='topics', case_id=source['id'], request_key='brand', brand_reference=reference), 202)
    assert '支持排版' in AITask.objects.get(pk=task['id']).snapshot['brand']['context']
    product.owner = ctx['other']; product.save()
    post(ctx, 'ai/tasks', dict(kind='topics', case_id=source['id'], request_key='forbidden', brand_reference=reference), 400)


def test_handoff_and_return_create_new_version(ctx):
    from apps.conversations.models import Conversation, Message
    from apps.applications.models import ChatApplication
    row = channel(ctx, topic(ctx, case(ctx))); v = version(ctx, row)
    target = Application.objects.create(organization=ctx['org'], category=ctx['app'].category, name='图文', slug='write-image-text-copy', created_by=ctx['user'], kind='chat', visibility='organization')
    chat = ChatApplication.objects.create(application=target)
    h = post(ctx, 'handoffs', dict(channel_id=row['id'], version_id=v['id'], target_id=target.pk))
    assert f'/applications/{target.pk}/chat?' in h['url']
    assert '真实' in h['draft']['source']
    assert post(ctx, 'handoffs', dict(channel_id=row['id'], version_id=v['id'], target_id=target.pk), 200)['id'] == h['id']
    conversation = Conversation.objects.create(organization=ctx['org'], user=ctx['user'], chat_application=chat, title='创作')
    r = ctx['client'].patch(f"{ctx['root']}/handoffs/{h['id']}", dict(revision=h['revision'], conversation_id=str(conversation.pk)), format='json')
    assert r.status_code == 200, r.data
    run = Run.objects.create(organization=ctx['org'], owner=ctx['user'], status='succeeded', executor_key='agent-chat')
    message = Message.objects.create(conversation=conversation, role='assistant', content='图文生成回复', run=run)
    Message.objects.create(conversation=conversation, role='assistant', content='未完成，不回存')
    assert len(get(ctx, f"handoffs/{h['id']}/results")) == 1
    imported = post(ctx, f"handoffs/{h['id']}/results", dict(message_id=message.pk))
    assert imported['body']['body'] == '图文生成回复'
    assert imported['snapshot']['handoff_id'] == h['id']
    post(ctx, f"handoffs/{h['id']}/results", dict(message_id=message.pk), 200)
    assert Version.objects.count() == 2
    ctx['client'].force_authenticate(ctx['other'])
    assert ctx['client'].get(f"{ctx['root']}/handoffs/{h['id']}/results").status_code == 404


def test_run_stream_and_children_keep_private_boundary(ctx):
    from asgiref.sync import async_to_sync
    from modules.execution.api.streaming import _load_event_batch, StreamAccessLost
    source = case(ctx)
    task = post(ctx, 'ai/tasks', dict(kind='topics', case_id=source['id'], request_key='stream'), 202)
    run = Run.objects.get(pk=task['run_id'])
    child = Run.objects.create(organization=ctx['org'], owner=ctx['user'], parent=run, executor_key='agent-chat')
    root = f"/api/v1/organizations/{ctx['org'].pk}/runs/{run.pk}"
    assert ctx['client'].get(root + '/events').status_code == 200
    assert ctx['client'].get(root + '/stream', HTTP_ACCEPT='text/event-stream').status_code == 200
    kwargs = dict(user=ctx['user'], organization_id=ctx['org'].pk, run_id=run.pk, after=0, limit=100)
    assert async_to_sync(_load_event_batch)(**kwargs) == []
    ctx['client'].force_authenticate(ctx['other'])
    for run_id in [run.pk, child.pk]:
        for suffix in ['', '/events', '/stream', '/snapshot']:
            assert ctx['client'].get(f"/api/v1/organizations/{ctx['org'].pk}/runs/{run_id}{suffix}").status_code == 404
    ctx['app'].is_active = False; ctx['app'].save()
    with pytest.raises(StreamAccessLost):
        async_to_sync(_load_event_batch)(**kwargs)


def test_cross_organization_and_application_references_are_rejected(ctx):
    other_org = ctx['other'].owned_organizations.get()
    alien = Application.objects.create(organization=other_org, category=ctx['app'].category, name='另一个组织', slug='project-promotion', kind='custom', created_by=ctx['other'])
    source = Case.objects.create(organization=other_org, application=alien, owner=ctx['other'], title='私密', status='confirmed')
    post(ctx, 'topics', dict(title='跨组织', case_id=str(source.pk)), 404)
    post(ctx, 'ai/tasks', dict(kind='topics', case_id=str(source.pk), request_key='alien'), 404)
    assert ctx['client'].get(ctx['root'].replace(str(ctx['app'].pk) + '/project', str(alien.pk) + '/project') + '/cases').status_code == 404
    post(ctx, 'cases', dict(title='伪造所有者', owner=str(ctx['other'].pk)), 400)


def test_publication_requires_recheck_after_topic_changes(ctx):
    idea = topic(ctx, case(ctx)); row = channel(ctx, idea); v = version(ctx, row)
    row = get(ctx, f"channels/{row['id']}")
    row = post(ctx, f"channels/{row['id']}/versions/{v['id']}/confirm", dict(revision=row['revision']), 200)
    patch(ctx, 'topics', idea, dict(data={'angle': '不同角度'}))
    patch(ctx, 'channels', row, dict(status='published', data={'published_at': '2026-10-14T12:00:00+08:00'}), 409)
    fresh = version(ctx, row)
    row = get(ctx, f"channels/{row['id']}")
    row = post(ctx, f"channels/{row['id']}/versions/{fresh['id']}/confirm", dict(revision=row['revision']), 200)
    patch(ctx, 'channels', row, dict(status='published', data={'published_at': '2026-10-14T12:00:00+08:00'}))


@pytest.mark.parametrize('platform,body', [('xiaohongshu', {'title': '标题', 'body': '正文'}), ('douyin', {'title': '标题', 'body': '正文', 'script': '脚本'})])
def test_channel_specific_output_validation(ctx, platform, body):
    from rest_framework.exceptions import ValidationError
    row = channel(ctx, topic(ctx, case(ctx)), platform)
    t = post(ctx, 'ai/tasks', dict(kind='copy', channel_id=row['id'], request_key='invalid'), 202)
    with pytest.raises(ValidationError):
        ai.validate_result(AITask.objects.get(pk=t['id']), body)


def test_unknown_feedback_and_observation_date_not_insertion_order(ctx):
    row = publish(ctx, channel(ctx, topic(ctx, case(ctx))))
    post(ctx, 'feedback', dict(title='新观察', channel_id=row['id'], data=dict(observed_on='2026-10-15', views=0)))
    post(ctx, 'feedback', dict(title='补录旧数据', channel_id=row['id'], data=dict(observed_on='2026-10-14', views=100)))
    result = get(ctx, 'report')
    assert result['groups']['platforms'][0]['metrics']['views'] == dict(total=0, samples=1)
    assert result['groups']['platforms'][0]['metrics']['inquiries'] == dict(total=None, samples=0)
    post(ctx, 'feedback', dict(title='非法负值', channel_id=row['id'], data=dict(observed_on='2026-10-15', views=-1)), 400)


def test_install_and_real_run_creation(ctx, monkeypatch):
    from django.core.management import call_command
    from modules.execution.application.start_runs import start_application_run
    from modules.catalog.models import ApplicationRevision
    call_command('sync_app_center', package_id='project-promotion', organization_id=str(ctx['org'].pk))
    count = ApplicationRevision.objects.filter(application=ctx['app']).count()
    call_command('sync_app_center', package_id='project-promotion', organization_id=str(ctx['org'].pk))
    assert ApplicationRevision.objects.filter(application=ctx['app']).count() == count
    monkeypatch.setattr(ai, 'start_application_run', start_application_run)
    t = post(ctx, 'ai/tasks', dict(kind='case', instruction='开发记录', request_key='real-run'), 202)
    run = Run.objects.get(pk=t['run_id'])
    assert run.executor_key == 'project-promotion'
    assert run.status == 'queued'
    assert run.definition_snapshot

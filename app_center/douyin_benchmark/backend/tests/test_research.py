from datetime import timedelta
from unittest.mock import Mock
import pytest
from django.utils import timezone
from django.core.management import call_command
from .. import models as m
from ..research import comparison, record_observation, trend, scope_for, sample
from ..subscriptions import dispatch_due, growth_notice, make_digests
from ..research_runtime import validate_topics_report, validate_variants
from ..provider import CollectionError, normalize_work
from ..collector_config import LocalDTKClient
from ...runtime import execute
from .test_douyin import ctx, claim, add_work, content, script  # noqa: F401


@pytest.fixture(params=['organization', 'single-tenant'])
def workspace_ctx(ctx, settings, request):
    if request.param == 'single-tenant':
        settings.SINGLE_TENANT_MODE = True
        settings.SINGLE_TENANT_ORGANIZATION_ID = str(ctx.org.pk)
        ctx.root = f'/api/v1/applications/{ctx.app.pk}/douyin-benchmark'
    return ctx


@pytest.mark.parametrize('resource', [
    'creator-profiles', 'inspirations', 'ideas', 'publications',
    'subscriptions', 'notifications', 'digests',
])
def test_workspace_record_lists(workspace_ctx, resource):
    response = workspace_ctx.client.get(workspace_ctx.root + '/' + resource)
    assert response.status_code == 200, response.data
    assert response.data == {'count': 0, 'results': []}


def start(ctx, values, key='research-1'):
    return ctx.client.post(ctx.root + '/tasks', values, format='json', HTTP_IDEMPOTENCY_KEY=key)


def finish(task):
    task.run.status = 'succeeded'
    task.run.save(update_fields=['status'])


def other_account(ctx, owner=None):
    return m.Account.objects.create(organization=ctx.org, application=ctx.app, owner=owner or ctx.owner, source_url='https://www.douyin.com/user/other', name='其他账号')


def test_workspace_record_isolation_and_revision(workspace_ctx):
    ctx = workspace_ctx
    response = ctx.client.post(ctx.root + '/ideas', {'title': '新主题', 'tags': ['知识']}, format='json')
    assert response.status_code == 201, response.data
    idea = response.data
    url = ctx.root + '/ideas/' + idea['id']
    assert ctx.client.patch(url, {'revision': 1, 'notes': '补充'}, format='json').data['revision'] == 2
    assert ctx.client.patch(url, {'revision': 1, 'notes': '覆盖'}, format='json').status_code == 409
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.root + '/ideas').data['count'] == 0
    assert ctx.client.get(url).status_code == 404
    assert ctx.client.delete(url).status_code == 404


def test_private_relations_cannot_cross_owners(ctx):
    foreign = other_account(ctx, ctx.reader)
    work = m.Work.objects.create(account=foreign, platform_id='123', metadata=normalize_work(content()))
    assert ctx.client.post(ctx.root + '/inspirations', {'title': '偷看', 'work': str(work.pk)}, format='json').status_code == 400
    assert start(ctx, {'kind': 'refresh', 'work_ids': [str(work.pk)]}).status_code == 400
    assert start(ctx, {'kind': 'radar', 'account_ids': [str(foreign.pk)]}).status_code == 400


def test_default_profile_atomic_and_frozen_brief(workspace_ctx):
    ctx = workspace_ctx
    a = ctx.client.post(ctx.root + '/creator-profiles', {'name': 'A', 'positioning': '科普', 'experiences': '亲身实验', 'is_default': True}, format='json')
    assert a.status_code == 201, a.data
    b = ctx.client.post(ctx.root + '/creator-profiles', {'name': 'B', 'positioning': '美食', 'is_default': True}, format='json')
    assert b.status_code == 201, b.data
    assert m.CreatorProfile.objects.filter(is_default=True).count() == 1
    idea = ctx.client.post(ctx.root + '/ideas', {'title': '如何烹饪'}, format='json').data
    task_response = start(ctx, {'kind': 'topics', 'idea_id': idea['id']})
    assert task_response.status_code == 201, task_response.data
    task = m.Task.objects.get(pk=task_response.data['id'])
    assert task.account_id is None and task.owner_id == ctx.owner.pk
    assert task.input['brief']['positioning'] == '美食'
    assert task.input['brief']['theme'] == '如何烹饪'
    m.CreatorProfile.objects.filter(pk=b.data['id']).update(positioning='changed')
    task.refresh_from_db()
    assert task.input['brief']['profile']['positioning'] == '美食'


def test_workspace_task_idempotency_and_run_privacy(ctx):
    work = add_work(ctx)
    response = start(ctx, {'kind': 'refresh', 'work_ids': [str(work.pk)]})
    assert response.status_code == 201, response.data
    assert start(ctx, {'kind': 'refresh', 'work_ids': [str(work.pk)]}).data['id'] == response.data['id']
    assert start(ctx, {'kind': 'comments', 'work_ids': [str(work.pk)]}).status_code == 409
    task = m.Task.objects.get(pk=response.data['id'])
    assert task.run.input == {'task_id': str(task.pk)}
    from ..access import can_access_run
    assert can_access_run(ctx.owner, task.run)
    assert not can_access_run(ctx.reader, task.run)


def test_sample_balances_accounts_and_comparison_marks_missing(ctx):
    add_work(ctx)
    other = other_account(ctx)
    batch = m.Task.objects.create(account=other, kind='collect', request_key='other', request_hash='x')
    for index in range(3):
        data = normalize_work(content(index + 10))
        work = m.Work.objects.create(account=other, platform_id=data['platform_id'], metadata=data)
        m.Snapshot.objects.create(batch=batch, work=work, captured_at=timezone.now(), data=data)
    rows, coverage = sample(scope_for(ctx.app, ctx.owner), [ctx.account.pk, other.pk], 30)
    assert len(rows) == 4 and coverage['available'] == 4
    assert len({r['account_id'] for r in rows[:2]}) == 2
    result = comparison(scope_for(ctx.app, ctx.owner), [ctx.account.pk, other.pk], 30)
    assert all(r['outstanding_share'] is None for r in result['accounts'])
    assert all(r['medians']['comments'] is None for r in result['accounts'])
    assert start(ctx, {'kind': 'radar', 'group': '不存在'}).status_code == 400


def test_trend_preserves_zero_missing_negative_and_real_time(ctx):
    work = add_work(ctx)
    work.snapshot_set.all().delete()
    now = timezone.now()
    record_observation(ctx.task, work, {'likes': 10, 'comments': None, 'collects': 0}, now)
    next_task = m.Task.objects.create(account=ctx.account, kind='refresh', request_key='r', request_hash='r')
    record_observation(next_task, work, {'likes': 6, 'comments': 1, 'collects': 0}, now + timedelta(hours=2))
    result = trend(work)
    assert result[1]['delta'] == {'likes': -4, 'comments': None, 'collects': 0, 'shares': None}
    assert result[1]['per_hour']['likes'] == -2
    assert len(result) == 2
    assert not record_observation(next_task, work, {'likes': 99}, now)[1]


def test_backfill_is_idempotent(ctx):
    add_work(ctx)
    call_command('backfill_douyin_observations')
    call_command('backfill_douyin_observations')
    assert m.MetricObservation.objects.count() == 1


def test_refresh_does_not_change_collection_sample(ctx, monkeypatch):
    work = add_work(ctx)
    response = start(ctx, {'kind': 'refresh', 'work_ids': [str(work.pk)]})
    task = m.Task.objects.get(pk=response.data['id'])
    monkeypatch.setattr(LocalDTKClient, 'detail', lambda *_: content(likes=999))
    execute(*claim(task))
    assert m.Snapshot.objects.get(work=work).data['likes'] == 10
    assert m.MetricObservation.objects.get(task=task).data['likes'] == 999
    work.refresh_from_db()
    assert work.metadata['likes'] == 999


def test_comment_pagination_dedup_and_loop(ctx):
    client = LocalDTKClient(account=ctx.account)
    row = {'comment_id': 'c1', 'text': '为什么'}
    client.fetch = Mock(side_effect=[{'items': [row, row], 'has_more': True, 'cursor': 'x'}, {'items': [row], 'has_more': True, 'cursor': 'x'}])
    pages = client.comment_pages('123', 100)
    assert len(next(pages)[0]) == 1
    assert next(pages)[0] == []
    with pytest.raises(CollectionError, match='分页'):
        next(pages)


def test_comment_runtime_partial_and_needs_freeze(ctx, monkeypatch):
    work = add_work(ctx)
    response = start(ctx, {'kind': 'comments', 'work_ids': [str(work.pk)]})
    task = m.Task.objects.get(pk=response.data['id'])
    def pages(*args, **kwargs):
        yield [{'comment_id': 'c1', 'text': '如何选择？', 'digg_count': 0}], False
        raise CollectionError('timeout')
    monkeypatch.setattr(LocalDTKClient, 'comment_pages', pages)
    execute(*claim(task)); finish(task)
    batch = m.CommentBatch.objects.get(task=task)
    assert not batch.complete and batch.comments.count() == 1
    assert batch.comments.first().likes == 0
    needs = start(ctx, {'kind': 'needs', 'source_task_id': str(task.pk)}, 'needs-1')
    assert needs.status_code == 201, needs.data
    frozen = m.Task.objects.get(pk=needs.data['id']).input['comments']
    assert frozen[0]['text'] == '如何选择？'


def test_joint_suspends_and_resumes_with_namespaced_sources(ctx, monkeypatch):
    from modules.execution.runtime.child import _SuspendExecution
    work = add_work(ctx)
    data = normalize_work(content(2))
    other = m.Work.objects.create(account=ctx.account, platform_id=data['platform_id'], metadata=data)
    response = start(ctx, {'kind': 'joint', 'work_ids': [str(work.pk), str(other.pk)]})
    parent = m.Task.objects.get(pk=response.data['id'])
    payload, sink = claim(parent)
    sink.wait_for_children = Mock(side_effect=_SuspendExecution)
    with pytest.raises(_SuspendExecution):
        execute(payload, sink)
    children = list(m.Task.objects.filter(run__parent=parent.run))
    assert len(children) == 2
    for child in children:
        child.output = {'segments': [{'id': 's1', 'start': 0, 'end': 5, 'text': '例子'}], 'claims': []}
        child.save(update_fields=['output']); finish(child)
    mock = Mock(return_value={'claims': []})
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_claims', mock)
    execute(payload, sink)
    allowed = mock.call_args.args[4]
    assert allowed == {f'{child.pk}:s1' for child in children}
    assert m.Task.objects.filter(run__parent=parent.run).count() == 2


def test_subscription_growth_deduplicates_and_daily_digest(ctx):
    work = add_work(ctx)
    scope = scope_for(ctx.app, ctx.owner)
    m.Subscription.objects.create(**scope, account=ctx.account)
    now = timezone.now().replace(hour=0, minute=0, second=0)
    record_observation(ctx.task, work, {'likes': 0, 'comments': None}, now - timedelta(hours=2))
    task = m.Task.objects.create(account=ctx.account, kind='refresh', request_key='r2', request_hash='r2')
    point, _ = record_observation(task, work, {'likes': 100, 'comments': 100}, now - timedelta(hours=1))
    growth_notice(task, work, point); growth_notice(task, work, point)
    assert m.Notification.objects.filter(kind='growth').count() == 1
    make_digests(ctx.org.pk, now + timedelta(hours=2))
    make_digests(ctx.org.pk, now + timedelta(hours=2))
    assert m.Digest.objects.count() == 1
    assert m.Digest.objects.first().body['changes'][0]['delta']['likes'] == 100


def test_subscriptions_opt_in_dispatch_and_config_removal(ctx):
    scope = scope_for(ctx.app, ctx.owner)
    m.CollectorConfig.objects.create(**scope, user_agent='UA', cookies='test')
    response = ctx.client.post(ctx.root + '/subscriptions', {'account': str(ctx.account.pk)}, format='json')
    assert response.status_code == 201, response.data
    subscription = m.Subscription.objects.get(pk=response.data['id'])
    assert not subscription.enabled and subscription.next_run_at is None
    finish(ctx.task)
    subscription.enabled, subscription.next_run_at = True, timezone.now() - timedelta(days=3)
    subscription.save()
    dispatch_due(); dispatch_due()
    assert ctx.account.tasks.filter(input__subscription_id=str(subscription.pk)).count() == 1
    ctx.client.delete(ctx.root + '/collector-config')
    subscription.refresh_from_db()
    assert not subscription.enabled and subscription.next_run_at is None


def test_publication_requires_owned_work_and_private_script(ctx):
    work = add_work(ctx)
    body = {'work': str(work.pk), 'theme': '科普'}
    assert ctx.client.post(ctx.root + '/publications', body, format='json').status_code == 400
    ctx.account.is_owned = True; ctx.account.save()
    assert ctx.client.post(ctx.root + '/publications', body, format='json').status_code == 201
    assert ctx.client.post(ctx.root + '/publications', body, format='json').status_code == 409
    result = start(ctx, {'kind': 'review'})
    assert result.status_code == 201, result.data
    assert m.Task.objects.get(pk=result.data['id']).input['publications'][0]['theme'] == '科普'


def test_delete_account_preserves_authored_document_and_idea(ctx):
    work = add_work(ctx)
    result = start(ctx, {'kind': 'radar'})
    assert result.status_code == 201, result.data
    authored = m.Task.objects.create(account=ctx.account, work=work, kind='script', request_key='written', request_hash='written')
    version = m.ScriptVersion.objects.create(task=authored, revision=1, content=script())
    idea = m.Idea.objects.create(**scope_for(ctx.app, ctx.owner), title='独立选题', source_task=authored)
    assert ctx.client.delete(ctx.url).status_code == 204
    assert not m.Task.objects.filter(pk=result.data['id']).exists()
    authored.refresh_from_db()
    assert authored.account_id is None and authored.input == {}
    assert m.ScriptVersion.objects.filter(pk=version.pk).exists() and m.Idea.objects.filter(pk=idea.pk).exists()


def test_model_output_validation_rejects_unknown_references():
    with pytest.raises(ValueError):
        validate_topics_report({'topics': [{'title': '主题', 'angle': '角度', 'refs': ['fake']}]}, {'real'})
    with pytest.raises(ValueError):
        validate_variants({'hooks': []})


def test_variants_freeze_version_apply_conflict_and_keep_history(ctx):
    source = m.Task.objects.create(account=ctx.account, kind='script', request_key='script', request_hash='s', run=None)
    version = m.ScriptVersion.objects.create(task=source, revision=1, content=script())
    response = start(ctx, {'kind': 'variants', 'source_version_id': str(version.pk)})
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    finish(task)
    assert task.input['content'] == version.content
    variants = {key: [{'text': f'{key}{i}', 'angle': '观察角度'} for i in range(3)] for key in ['hooks', 'titles', 'covers']}
    m.ScriptVersion.objects.create(task=task, revision=1, content=variants)
    saved = ctx.client.post(f'{ctx.root}/tasks/{task.pk}/versions', {'revision': 1, 'content': variants}, format='json')
    assert saved.status_code == 201, saved.data
    download = ctx.client.get(f'{ctx.root}/tasks/{task.pk}/versions/{saved.data["id"]}/download')
    assert download.status_code == 200 and '封面短句'.encode() in download.content
    result = ctx.client.post(f'{ctx.root}/tasks/{task.pk}/apply', {'revision': 1, 'title': '新标题', 'hook': '新开头'}, format='json')
    assert result.status_code == 201, result.data
    assert result.data['content']['narration'].startswith('新开头')
    version.refresh_from_db()
    assert version.content['title'] != '新标题'
    assert ctx.client.post(f'{ctx.root}/tasks/{task.pk}/apply', {'revision': 1, 'title': '覆盖'}, format='json').status_code == 409


def test_cancelled_refresh_cannot_write_a_late_response(ctx, monkeypatch):
    work = add_work(ctx)
    response = start(ctx, {'kind': 'refresh', 'work_ids': [str(work.pk)]})
    task = m.Task.objects.get(pk=response.data['id'])
    payload, sink = claim(task)
    def late(*args):
        sink.cancelled = True
        return content(likes=1234)
    monkeypatch.setattr(LocalDTKClient, 'detail', late)
    with pytest.raises(InterruptedError):
        execute(payload, sink)
    assert not m.MetricObservation.objects.filter(task=task).exists()
    work.refresh_from_db()
    assert work.metadata['likes'] == 10


def test_scheduler_serializes_accounts_and_pauses_removed_members(ctx):
    from apps.enterprise.models import Membership
    scope = scope_for(ctx.app, ctx.owner)
    m.CollectorConfig.objects.create(**scope, user_agent='UA', cookies='test')
    finish(ctx.task)
    other = other_account(ctx)
    for account in [ctx.account, other]:
        m.Subscription.objects.create(**scope, account=account, enabled=True, next_run_at=timezone.now() - timedelta(days=2))
    dispatch_due(); dispatch_due()
    assert m.Task.objects.filter(input__subscription_id__isnull=False).count() == 1
    task = m.Task.objects.filter(input__subscription_id__isnull=False).get()
    finish(task)
    Membership.objects.filter(organization=ctx.org, user=ctx.owner).update(is_active=False)
    dispatch_due()
    assert m.Subscription.objects.filter(blocked_reason__contains='权限').count() == 1


def test_publication_groups_are_descriptive_and_keep_missing_values(ctx):
    from ..research import publication_summary
    work = add_work(ctx)
    m.Publication.objects.create(**scope_for(ctx.app, ctx.owner), work=work, theme='知识', title='标题', hook='提问开场')
    result = publication_summary(scope_for(ctx.app, ctx.owner))
    assert result['by_theme'][0]['sample_count'] == 1
    assert result['by_theme'][0]['medians']['comments'] is None
    assert result['by_expression'][0]['label'] == '标题 / 提问开场'


def test_radar_input_budget_and_media_url_redaction():
    from ..research_runtime import radar_evidence, model_evidence
    import json
    rows = [{'id': str(i), 'title': '题' * 1000, 'transcript': '话' * 4000, 'description': '说' * 2000, 'video_url': 'private-signed-url'} for i in range(200)]
    result = radar_evidence(rows)
    assert len(json.dumps(result, ensure_ascii=False)) <= 150000
    assert 'private-signed-url' not in json.dumps(result)
    assert model_evidence({'work': {'video_url': 'secret', 'likes': 0}}) == {'work': {'likes': 0}}

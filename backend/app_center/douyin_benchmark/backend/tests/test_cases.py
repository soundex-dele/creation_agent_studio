import copy

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from apps.templates.models import Template, TemplateCategory
from .. import models as m
from ..cases import freeze_cases
from ..research import scope_for
from ...runtime import execute
from .test_douyin import ctx, add_work, post, claim, script  # noqa: F401
from .test_research import workspace_ctx, finish, start, other_account  # noqa: F401


def save(ctx, work, **body):
    return ctx.client.post(ctx.root + f'/works/{work.pk}/case', body, format='json')


def completed(ctx, work, kind='breakdown', key='breakdown'):
    response = post(ctx, {'kind': kind, 'work_id': str(work.pk)}, key)
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    task.output = {'segments': [{'id': 's1', 'start': 0, 'end': 4, 'text': '用具体问题说明原理。'}],
        'claims': [{'type': 'inference', 'text': '开头可能吸引目标受众。', 'refs': ['s1']}],
        'frames': [{'id': 'f1', 'time': 1, 'key': 'private-media-key'}]}
    task.save(update_fields=['output'])
    finish(task)
    return task


def library_get(ctx, path='/api/v1/templates/', **params):
    return ctx.client.get(path, params, HTTP_X_ORGANIZATION_ID=str(ctx.org.pk))


def test_save_update_dedup_and_source_deletion(workspace_ctx):
    ctx = workspace_ctx
    work = add_work(ctx)
    initial_tasks = m.Task.objects.count()
    response = save(ctx, work, title='我的案例', summary='我的摘要', tags=['科普'])
    assert response.status_code == 201, response.data
    case = Template.objects.get(pk=response.data['case_id'])
    assert case.status == 'draft' and case.copyright_mode == 'reference'
    assert case.source_content == work.metadata['description']
    assert m.Task.objects.count() == initial_tasks  # Saving does not trigger AI.
    assert save(ctx, work).data == {'case_id': case.pk, 'result': 'existing'}
    task = completed(ctx, work)
    preview = ctx.client.get(ctx.root + f'/works/{work.pk}/case').data
    assert preview['task_id'] == str(task.pk) and preview['case_id'] == case.pk
    assert '用具体问题' in preview['source_content']
    assert save(ctx, work).data['result'] == 'existing'
    case.refresh_from_db()
    assert case.source_content == work.metadata['description']
    assert save(ctx, work, action='update', task_id=str(task.pk), title='不应覆盖').status_code == 200
    case.refresh_from_db()
    assert case.title == '我的案例' and case.summary == '我的摘要' and case.tags == ['科普']
    assert case.source_content == '用具体问题说明原理。'
    section = case.analysis_sections.get()
    assert section.title == '初步推测' and '0–4秒' in section.evidence_quote
    assert 'private-media-key' not in str(case.source_snapshot)
    detail = library_get(ctx, f'/api/v1/templates/{case.pk}/').data
    assert detail['source_navigation']['available'] is True
    ctx.account.delete()
    case.refresh_from_db()
    detail = library_get(ctx, f'/api/v1/templates/{case.pk}/').data
    assert detail['source_navigation'] == {'available': False}
    assert detail['source_content'] == '用具体问题说明原理。'


def test_image_album_description_and_stable_platform_key(ctx):
    work = add_work(ctx)
    work.metadata['kind'] = 'image_album'; work.save()
    case_id = save(ctx, work).data['case_id']
    assert Template.objects.get(pk=case_id).content_type == 'social_post'
    other = other_account(ctx)
    same_work = m.Work.objects.create(account=other, platform_id=work.platform_id, metadata=work.metadata)
    assert save(ctx, same_work).data['case_id'] == case_id
    original = Template.objects.get(pk=case_id)
    with pytest.raises(IntegrityError), transaction.atomic():
        Template.objects.create(category=original.category, created_by=ctx.owner, organization=ctx.org,
            title='重复', source_kind='douyin', source_key=original.source_key)


def test_media_match_and_explicit_source_validation(ctx):
    work = add_work(ctx)
    task = completed(ctx, work)
    work.media_key = 'replacement'; work.save()
    assert ctx.client.get(ctx.root + f'/works/{work.pk}/case').data['task_id'] is None
    assert ctx.client.get(ctx.root + f'/works/{work.pk}/case', {'task_id': str(task.pk)}).data['task_id'] == str(task.pk)
    foreign = m.Work.objects.create(account=other_account(ctx), platform_id='123', metadata=work.metadata)
    assert save(ctx, foreign, task_id=str(task.pk)).status_code == 404
    task.run.status = 'failed'; task.run.save()
    assert save(ctx, work, task_id=str(task.pk)).status_code == 404
    assert ctx.client.get(ctx.root + f'/works/{work.pk}/case', {'task_id': 'invalid'}).status_code == 400


def test_private_and_public_visibility_and_destinations(ctx):
    work = add_work(ctx)
    case_id = save(ctx, work).data['case_id']
    assert library_get(ctx, mine='true', source_kind='douyin').data['count'] == 1
    assert ctx.client.get(ctx.url + '/works').data['items'][0]['case_id'] == case_id
    assert ctx.client.get(ctx.root + '/works').data['results'][0]['case_id'] == case_id
    assert library_get(ctx, '/api/v1/templates/douyin_applications/').data == [{'id': ctx.app.pk, 'name': ctx.app.name}]
    ctx.client.force_authenticate(ctx.reader)
    assert library_get(ctx).data['count'] == 0
    assert library_get(ctx, f'/api/v1/templates/{case_id}/').status_code == 404
    assert save(ctx, work).status_code == 404
    assert start(ctx, {'kind': 'article', 'theme': '主题', 'positioning': '定位', 'case_ids': [case_id]}).status_code == 400
    Template.objects.filter(pk=case_id).update(status='published')
    public = library_get(ctx, f'/api/v1/templates/{case_id}/').data
    assert public['source_navigation'] is None
    assert 'source_snapshot' not in public and 'source_key' not in public
    assert start(ctx, {'kind': 'article', 'theme': '主题', 'positioning': '定位', 'case_ids': [case_id]}, 'public').status_code == 201
    ctx.app.is_active = False; ctx.app.save()
    assert library_get(ctx, '/api/v1/templates/douyin_applications/').data == []
    assert save(ctx, work).status_code == 404


def test_other_organization_and_legacy_cases(ctx):
    work = add_work(ctx)
    own = Template.objects.get(pk=save(ctx, work).data['case_id'])
    outsider = get_user_model().objects.create_user(username='other-org')
    org = outsider.owned_organizations.get()
    foreign = Template.objects.create(created_by=ctx.owner, organization=org, category=own.category, title='其他组织')
    legacy = Template.objects.create(created_by=ctx.owner, category=own.category, title='历史案例')
    assert library_get(ctx, f'/api/v1/templates/{foreign.pk}/').status_code == 404
    assert library_get(ctx, f'/api/v1/templates/{legacy.pk}/').status_code == 200
    response = ctx.client.post(ctx.root.replace(str(ctx.org.pk), str(org.pk)) + f'/works/{work.pk}/case', {}, format='json')
    assert response.status_code in [403, 404]


@pytest.mark.parametrize('kind', ['topics', 'article', 'script'])
def test_cases_reach_creation_and_are_frozen(ctx, monkeypatch, kind):
    work = add_work(ctx)
    completed(ctx, work)
    case = Template.objects.get(pk=save(ctx, work).data['case_id'])
    result = start(ctx, {'kind': kind, 'theme': '新的主题', 'positioning': '科普', 'case_ids': [case.pk]})
    assert result.status_code == 201, result.data
    task = m.Task.objects.get(pk=result.data['id'])
    frozen = copy.deepcopy(task.input['reference']['cases'])
    Template.objects.filter(pk=case.pk).update(source_content='修改后的正文')
    calls = []
    def model(active, prompt, data, *args, **kwargs):
        calls.append(data)
        assert data['reference']['cases'] == frozen
        if kind == 'topics':
            return {'topics': [{'title': f'主题{i}', 'angle': '角度', 'hook': '开头'} for i in range(3)]}
        return script() if kind == 'script' else {'title': '新文章', 'body': '新的正文', 'notes': []}
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    execute(*claim(task))
    assert calls
    finish(task)
    if kind == 'topics':
        inherited = start(ctx, {'kind': 'article', 'source_task_id': str(task.pk)}, 'inherited')
        assert inherited.status_code == 201, inherited.data
        assert m.Task.objects.get(pk=inherited.data['id']).input['reference']['cases'] == frozen
        assert start(ctx, {'kind': 'article', 'source_task_id': str(task.pk), 'case_ids': []}, 'replace').status_code == 400
    case.delete()
    task.refresh_from_db()
    assert task.input['reference']['cases'] == frozen
    assert ctx.client.get(ctx.root + f'/tasks/{task.pk}').data['output']['case_references'] == frozen
    assert start(ctx, {'kind': 'article', 'theme': '主题', 'positioning': '定位', 'case_ids': [case.pk or frozen[0]['id']]}, 'deleted').status_code == 400
    if kind == 'topics':
        assert start(ctx, {'kind': 'script', 'source_task_id': str(task.pk)}, 'inaccessible').status_code == 400


def test_no_implicit_cases_and_size_validation(ctx):
    work = add_work(ctx)
    case = Template.objects.get(pk=save(ctx, work).data['case_id'])
    base = {'kind': 'article', 'theme': '主题', 'positioning': '定位'}
    plain = start(ctx, base)
    assert 'cases' not in m.Task.objects.get(pk=plain.data['id']).input['reference']
    assert start(ctx, {**base, 'case_ids': [case.pk] * 4}, 'many').status_code == 400
    case.source_content = '字' * 180001; case.save()
    assert start(ctx, {**base, 'case_ids': [case.pk]}, 'huge').status_code == 400
    case.source_content = '正文'; case.status = 'archived'; case.save()
    assert start(ctx, {**base, 'case_ids': [case.pk]}, 'archive').status_code == 400


def test_unselected_research_does_not_inherit_cases(ctx):
    work = add_work(ctx)
    task = completed(ctx, work)
    case = Template.objects.get(pk=save(ctx, work).data['case_id'])
    task.output['cases'] = freeze_cases(scope_for(ctx.app, ctx.owner), [case.pk]); task.save()
    result = start(ctx, {'kind': 'topics', 'source_task_id': str(task.pk), 'theme': '主题', 'positioning': '定位'})
    assert result.status_code == 201, result.data
    assert 'cases' not in m.Task.objects.get(pk=result.data['id']).input['reference']


@pytest.mark.parametrize('kind', ['topics', 'article', 'script'])
def test_all_creation_prompts_treat_cases_as_external_data(ctx, monkeypatch, kind):
    from .. import analysis
    seen = []
    monkeypatch.setattr(analysis, 'generate_json', lambda **kwargs: seen.append(kwargs) or {})
    ctx.task.kind = kind
    ctx.task.input = {'reference': {'cases': [{'id': 1, 'title': '参考'}]}}
    analysis.call_model(ctx.task, '原任务要求', {'reference': ctx.task.input['reference']}, {})
    assert 'reference.cases' in seen[0]['instruction']
    assert '不将原作者经历改写为用户经历' in seen[0]['instruction']


def test_destination_requires_run_access(ctx):
    from apps.applications.models import ApplicationAccessGrant
    from apps.enterprise.models import Membership
    ctx.app.visibility = 'restricted'; ctx.app.save()
    Membership.objects.filter(organization=ctx.org, user=ctx.reader).update(role=Membership.Role.VIEWER)
    grant = ApplicationAccessGrant.objects.create(application=ctx.app, user=ctx.reader, role='viewer')
    ctx.client.force_authenticate(ctx.reader)
    assert library_get(ctx, '/api/v1/templates/douyin_applications/').data == []
    grant.role = 'user'; grant.save()
    assert library_get(ctx, '/api/v1/templates/douyin_applications/').data == [{'id': ctx.app.pk, 'name': ctx.app.name}]


def test_account_api_deletion_preserves_cases_and_historical_references(ctx):
    work = add_work(ctx)
    source = completed(ctx, work)
    case_id = save(ctx, work).data['case_id']
    response = start(ctx, {'kind': 'topics', 'theme': '主题', 'positioning': '科普',
        'source_task_id': str(source.pk), 'case_ids': [case_id]})
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    frozen = copy.deepcopy(task.input['reference']['cases'])
    finish(task)
    assert ctx.client.delete(ctx.url).status_code == 204
    assert Template.objects.filter(pk=case_id).exists()
    assert library_get(ctx, f'/api/v1/templates/{case_id}/').data['source_navigation'] == {'available': False}
    assert ctx.client.get(ctx.root + f'/tasks/{task.pk}').data['output']['case_references'] == frozen

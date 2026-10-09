import copy
from unittest.mock import Mock
import pytest
from .. import models as m
from ..owned import CONTENT_FIELDS, make_prompt, validate_report, validate_owned_topics
from ..research import scope_for
from ...runtime import execute
from .test_douyin import ctx, claim, add_work, script  # noqa: F401
from .test_research import start, finish, other_account


def setup_profile(ctx, account=None):
    account = account or ctx.account
    account.is_owned = True
    account.save()
    response = ctx.client.post(ctx.root + '/creator-profiles', {'name': account.name or '我', 'account': str(account.pk)}, format='json')
    assert response.status_code == 201, response.data
    return m.CreatorProfile.objects.get(pk=response.data['id'])


def content(positioning='科学实验'):
    result = {k: '真实表达' for k in CONTENT_FIELDS}
    result.update(positioning=positioning, rules='先讲具体问题，不空泛总结', examples='我做过一个小实验。')
    result['prompt'] = make_prompt(result)
    return result


def confirm(ctx, profile, value=None, **extra):
    response = ctx.client.post(f'{ctx.root}/creator-profiles/{profile.pk}/voice-versions',
        {'revision': profile.revision, 'content': value or content(), **extra}, format='json')
    assert response.status_code == 200, response.data
    profile.refresh_from_db()
    return response.data['version']


def sample(ctx, profile, text='我做过一个小实验。', **extra):
    response = ctx.client.post(ctx.root + '/voice-samples', {'profile': str(profile.pk), 'title': '真实文案', 'text': text, **extra}, format='json')
    assert response.status_code == 201, response.data
    return response.data


def test_own_account_creation_and_filters(ctx):
    finish(ctx.task)
    result = ctx.client.post(ctx.root + '/accounts', {'source': ctx.account.source_url, 'is_owned': True}, format='json', HTTP_IDEMPOTENCY_KEY='owned')
    assert result.status_code == 200 and result.data['is_owned']
    other_account(ctx)
    assert ctx.client.get(ctx.root + '/accounts?owned=true').data['count'] == 1
    assert ctx.client.get(ctx.root + '/accounts?owned=false').data['count'] == 1


def test_profile_binding_private_and_unique(ctx):
    foreign = other_account(ctx, ctx.reader)
    assert ctx.client.post(ctx.root + '/creator-profiles', {'name': 'wrong', 'account': str(foreign.pk)}, format='json').status_code == 400
    assert ctx.client.post(ctx.root + '/creator-profiles', {'name': 'wrong', 'account': str(ctx.account.pk)}, format='json').status_code == 400
    p = setup_profile(ctx)
    duplicate = ctx.client.post(ctx.root + '/creator-profiles', {'name': 'duplicate', 'account': str(ctx.account.pk)}, format='json')
    assert duplicate.status_code in [400, 409]
    assert ctx.client.patch(f'{ctx.root}/creator-profiles/{p.pk}', {'revision': p.revision, 'account': None}, format='json').status_code == 400


def test_sample_reuses_transcript_and_prevents_cross_account(ctx):
    p = setup_profile(ctx)
    work = add_work(ctx)
    task = m.Task.objects.create(account=ctx.account, work=work, kind='transcribe', request_key='done', request_hash='x', input={'media_key': work.media_key})
    task.run = ctx.task.run
    ctx.task.run = None
    ctx.task.save()
    task.output = {'text': '实际口播正文'}
    task.save()
    finish(task)
    row = sample(ctx, p, '', work=str(work.pk))
    assert row['text'] == '实际口播正文' and str(row['source_task']) == str(task.pk)
    other = other_account(ctx)
    work2 = m.Work.objects.create(account=other, platform_id='other', metadata={})
    assert ctx.client.post(ctx.root + '/voice-samples', {'profile': str(p.pk), 'title': '错', 'work': str(work2.pk)}, format='json').status_code == 400


def test_image_sample_imports_published_caption_without_transcription(ctx):
    p = setup_profile(ctx)
    work = add_work(ctx)
    caption = '第一段，自己的真实观点。\n第二段，保留换行与完整文案。 #成长'
    work.metadata.update(kind='image_album', title='只是一段标题', description=caption)
    work.save()
    count = m.Task.objects.count()
    row = sample(ctx, p, '', work=str(work.pk))
    assert row['text'] == caption and row['work_kind'] == 'image_album'
    assert row['source_task'] is None and m.Task.objects.count() == count
    manual = sample(ctx, p, '我的手动校正版', work=str(work.pk))
    assert manual['text'] == '我的手动校正版'
    response = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)})
    assert response.status_code == 201
    assert caption in [s['text'] for s in m.Task.objects.get(pk=response.data['id']).input['voice_samples']]


def test_caption_recovery_respects_revision_and_never_overwrites_existing_text(ctx):
    p = setup_profile(ctx)
    work = add_work(ctx)
    work.metadata.update(kind='image_album', description='发布文案')
    work.save()
    legacy = m.VoiceSample.objects.create(**scope_for(ctx.app, ctx.owner), profile=p, work=work, title='旧样本', text='')
    url = f'{ctx.root}/voice-samples/{legacy.pk}'
    assert ctx.client.patch(url, {'revision': 0, 'import_caption': True}, format='json').status_code == 409
    response = ctx.client.patch(url, {'revision': 1, 'import_caption': True}, format='json')
    assert response.status_code == 200 and response.data['text'] == '发布文案'
    assert ctx.client.patch(url, {'revision': 2, 'import_caption': True}, format='json').status_code == 400
    legacy.refresh_from_db()
    assert legacy.text == '发布文案' and legacy.revision == 2
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.patch(url, {'revision': 2, 'import_caption': True}, format='json').status_code == 404


def test_missing_image_caption_is_not_replaced_with_title_or_video_description(ctx):
    p = setup_profile(ctx)
    work = add_work(ctx)
    video = sample(ctx, p, '', work=str(work.pk))
    assert video['text'] == ''  # Video descriptions are not spoken transcripts.
    work.metadata.update(kind='image_album', title='只有标题', description='')
    work.save()
    row = sample(ctx, p, '', work=str(work.pk))
    assert row['text'] == ''
    assert ctx.client.patch(f"{ctx.root}/voice-samples/{row['id']}", {'revision': 1, 'import_caption': True}, format='json').status_code == 400


def test_analysis_freezes_samples_excludes_rejected_and_requires_body(ctx):
    p = setup_profile(ctx)
    work = add_work(ctx)
    row = sample(ctx, p, '', work=str(work.pk))
    assert start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)}).status_code == 400
    result = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk), 'analysis_mode': 'positioning'})
    assert result.status_code == 201, result.data
    title_task = m.Task.objects.get(pk=result.data['id'])
    assert title_task.input['style_sample_count'] == 0
    sample(ctx, p, '不要学习', usage='exclude')
    ctx.client.patch(f"{ctx.root}/voice-samples/{row['id']}", {'revision': 1, 'text': '我的真实正文'}, format='json')
    result = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)}, 'style')
    task = m.Task.objects.get(pk=result.data['id'])
    m.VoiceSample.objects.filter(pk=row['id']).update(text='后来修改')
    task.refresh_from_db()
    assert len(task.input['voice_samples']) == 1
    assert task.input['voice_samples'][0]['text'] == '我的真实正文'


def test_report_validates_actual_quotes_and_style_sources():
    samples = [{'id': 's', 'title': '标题', 'text': '原文只说这些', 'usage': 'style'}]
    report = {'content': content(), 'findings': [{'category': 'keep', 'sample_id': 's', 'quote': '原文', 'text': '表达习惯'}]}
    assert validate_report(report, samples, 'style')['content']['prompt'].startswith('【账号定位】')
    for changes in [{'sample_id': 'foreign'}, {'quote': '编造'}, {'category': 'bad'}]:
        broken = copy.deepcopy(report)
        broken['findings'][0].update(changes)
        with pytest.raises(ValueError): validate_report(broken, samples, 'style')
    samples[0]['usage'] = 'content'
    with pytest.raises(ValueError): validate_report(report, samples, 'style')
    report['findings'][0]['category'] = 'positioning'
    assert validate_report(report, samples, 'positioning')['content']['rules'] == ''


def test_analysis_runtime_and_confirmation_keeps_previous_version(ctx, monkeypatch):
    p = setup_profile(ctx)
    v1 = confirm(ctx, p)
    row = sample(ctx, p)
    response = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)})
    task = m.Task.objects.get(pk=response.data['id'])
    report = {'content': content('新的方向'), 'findings': [{'category': 'keep', 'sample_id': row['id'], 'quote': '小实验', 'text': '用真实案例表达'}]}
    def model(*args, **kwargs):
        task.refresh_from_db()
        assert task.stage == '分析账号定位与文风'
        assert task.run.status == 'running'
        return report
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    execute(*claim(task))
    task.refresh_from_db()
    assert task.output['warning'] and task.output['voice_evidence'][0]['text'] == row['text']
    p.refresh_from_db()
    assert str(p.active_version_id) == v1['id']
    finish(task)
    v2 = confirm(ctx, p, task.output['content'], source_task_id=str(task.pk))
    assert v2['number'] == 2 and v2['evidence'][0]['text'] == row['text']
    stale = ctx.client.post(f'{ctx.root}/creator-profiles/{p.pk}/voice-versions', {'revision': 1, 'content': content()}, format='json')
    assert stale.status_code == 409
    activate = ctx.client.post(f"{ctx.root}/creator-profiles/{p.pk}/voice-versions/{v1['id']}/activate", {'revision': p.revision}, format='json')
    assert activate.status_code == 200
    p.refresh_from_db()
    assert str(p.active_version_id) == v1['id'] and p.voice_versions.count() == 2


def test_two_accounts_frozen_creation_and_explicit_shared_material(ctx, monkeypatch):
    a = setup_profile(ctx)
    b = setup_profile(ctx, other_account(ctx))
    scope = scope_for(ctx.app, ctx.owner)
    included = m.Inspiration.objects.create(**scope, title='可用经历', kind='text', text='共同的真实案例')
    m.Inspiration.objects.create(**scope, title='未选经历', kind='text', text='不应泄露到提示词')
    a.shared_inspiration_ids = [str(included.pk)]
    a.save()
    va = confirm(ctx, a, content('科学'))
    vb = confirm(ctx, b, content('美食'))
    ta = start(ctx, {'kind': 'topics', 'target_account_id': str(a.account_id)}, 'a')
    tb = start(ctx, {'kind': 'topics', 'target_account_id': str(b.account_id)}, 'b')
    assert ta.status_code == tb.status_code == 201
    task_a, task_b = m.Task.objects.get(pk=ta.data['id']), m.Task.objects.get(pk=tb.data['id'])
    assert task_a.input['brief']['voice_version_id'] == va['id']
    assert task_b.input['brief']['voice_version_id'] == vb['id']
    assert task_a.input['brief']['shared_materials'][0]['text'] == included.text
    assert task_b.input['brief']['shared_materials'] == []
    assert '未选经历' not in str(task_a.input)
    topics = {'topics': [dict(title=f'主题{i}', angle='角度', hook='开头', pillar='实验', reason='适合定位', materials_needed='补充真实过程', duplicate_note='已采集样本中未发现重复') for i in range(3)]}
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', Mock(return_value=topics))
    execute(*claim(task_a))
    task_a.refresh_from_db()
    assert task_a.output['topics'][0]['pillar'] == '实验'
    finish(task_a)
    confirm(ctx, a, content('新定位'))
    included.text = '修改后的素材'
    included.save()
    response = start(ctx, {'kind': 'script', 'source_task_id': str(task_a.pk), 'target_account_id': str(a.account_id)}, 'script')
    assert response.status_code == 201, response.data
    created = m.Task.objects.get(pk=response.data['id'])
    assert created.input['brief']['voice_version_id'] == va['id']
    assert created.input['brief']['shared_materials'][0]['text'] == '共同的真实案例'
    model = Mock(return_value=script())
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    execute(*claim(created))
    assert m.ScriptVersion.objects.filter(task=created).count() == 1
    assert model.call_args.args[2]['brief']['voice_profile']['prompt'] == va['content']['prompt']
    assert start(ctx, {'kind': 'script', 'source_task_id': str(task_a.pk), 'target_account_id': str(b.account_id)}, 'bad-script').status_code == 400
    assert start(ctx, {'kind': 'topics', 'target_account_id': str(b.account_id), 'profile_id': str(a.pk)}, 'bad-profile').status_code == 400


def test_owned_creation_never_uses_other_default(ctx):
    setup_profile(ctx)
    m.CreatorProfile.objects.create(**scope_for(ctx.app, ctx.owner), name='默认', positioning='无关定位', is_default=True)
    response = start(ctx, {'kind': 'topics', 'target_account_id': str(ctx.account.pk)})
    assert response.status_code == 400
    assert not m.Task.objects.filter(kind='topics').exists()


def test_voice_private_api_and_shared_materials(ctx):
    p = setup_profile(ctx)
    s = sample(ctx, p)
    version = confirm(ctx, p)
    foreign = m.Inspiration.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.reader, title='私密', kind='text')
    assert ctx.client.patch(f'{ctx.root}/creator-profiles/{p.pk}', {'revision': p.revision, 'shared_inspiration_ids': [str(foreign.pk)]}, format='json').status_code == 400
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.root + '/voice-samples').data['count'] == 0
    assert ctx.client.get(f"{ctx.root}/voice-samples/{s['id']}").status_code == 404
    assert ctx.client.get(f'{ctx.root}/creator-profiles/{p.pk}/voice-versions').status_code == 404
    assert ctx.client.post(f"{ctx.root}/creator-profiles/{p.pk}/voice-versions/{version['id']}/activate", {'revision': p.revision}, format='json').status_code == 404
    assert start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)}).status_code == 404


def test_account_removal_preserves_confirmed_profile_samples_and_documents(ctx):
    p = setup_profile(ctx)
    w = add_work(ctx)
    s = sample(ctx, p, work=str(w.pk))
    version = confirm(ctx, p)
    topic_response = start(ctx, {'kind': 'topics', 'target_account_id': str(ctx.account.pk)})
    topic = m.Task.objects.get(pk=topic_response.data['id'])
    topic.output = {'topics': [{'title': '题', 'angle': '角度', 'hook': '开头'}]}
    topic.save()
    finish(topic)
    response = start(ctx, {'kind': 'script', 'source_task_id': str(topic.pk)}, 'script')
    document = m.Task.objects.get(pk=response.data['id'])
    m.ScriptVersion.objects.create(task=document, revision=1, content=script())
    assert ctx.client.delete(ctx.url).status_code == 204
    p.refresh_from_db()
    assert p.account_id is None and str(p.active_version_id) == version['id']
    assert m.VoiceSample.objects.get(pk=s['id']).text == s['text']
    assert ctx.client.get(f"{ctx.root}/voice-samples/{s['id']}").data['source_missing']
    assert m.ScriptVersion.objects.filter(task=document).exists()


def test_owned_topics_require_explanations():
    with pytest.raises(ValueError):
        validate_owned_topics({'topics': [{'title': 'a', 'angle': 'b', 'hook': 'c'}] * 3})


def test_failed_or_cancelled_analysis_never_replaces_confirmed_version(ctx, monkeypatch):
    p = setup_profile(ctx)
    version = confirm(ctx, p)
    sample(ctx, p)
    response = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)})
    t = m.Task.objects.get(pk=response.data['id'])
    model = Mock(return_value={'content': {}, 'findings': []})
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    with pytest.raises(RuntimeError): execute(*claim(t))
    assert model.call_count == 2
    p.refresh_from_db()
    assert str(p.active_version_id) == version['id'] and p.voice_samples.count() == 1
    retry = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)}, 'retry')
    cancelled = m.Task.objects.get(pk=retry.data['id'])
    payload, sink = claim(cancelled)
    sink.cancelled = True
    with pytest.raises(InterruptedError): execute(payload, sink)
    assert p.voice_versions.count() == 1


def test_partial_transcript_analysis_and_cross_profile_activation(ctx):
    p = setup_profile(ctx)
    sample(ctx, p)
    work = add_work(ctx)
    sample(ctx, p, '', work=str(work.pk))
    response = start(ctx, {'kind': 'voice_analysis', 'target_account_id': str(ctx.account.pk)})
    t = m.Task.objects.get(pk=response.data['id'])
    assert t.input['style_sample_count'] == 1 and len(t.input['voice_samples']) == 2
    other = setup_profile(ctx, other_account(ctx))
    version = confirm(ctx, other)
    response = ctx.client.post(f"{ctx.root}/creator-profiles/{p.pk}/voice-versions/{version['id']}/activate", {'revision': p.revision}, format='json')
    assert response.status_code == 404
    assert ctx.client.patch(f'{ctx.root}/creator-profiles/{p.pk}', {'revision': p.revision, 'shared_inspiration_ids': ['invalid']}, format='json').status_code == 400

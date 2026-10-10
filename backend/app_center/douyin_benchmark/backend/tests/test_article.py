from unittest.mock import Mock
import pytest
from .. import models as m
from ..article import validate_article
from ...runtime import execute
from .test_douyin import ctx, claim  # noqa: F401
from .test_owned import setup_profile, confirm, content
from .test_research import start, finish, other_account


def topics_for(ctx):
    profile = setup_profile(ctx)
    voice = confirm(ctx, profile)
    response = start(ctx, {'kind': 'topics', 'target_account_id': str(ctx.account.pk)})
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    task.output = {'topics': [{'title': f'选题{i}', 'angle': '具体解释', 'hook': '从真实困惑开始'} for i in range(3)]}
    task.save()
    finish(task)
    return profile, voice, task


def article_content():
    return {'title': '用自己的方式表达', 'body': '先说一个具体的问题。\n\n把道理说清楚，比堆砌漂亮的话更重要。', 'notes': ['发布前核对案例事实']}


def test_article_uses_topic_voice_snapshot_and_saves_editable_version(ctx, monkeypatch):
    profile, voice, topics = topics_for(ctx)
    confirm(ctx, profile, content('新的账号方向'))
    values = {'kind': 'article', 'source_task_id': str(topics.pk), 'topic_index': 1, 'target_account_id': str(ctx.account.pk)}
    response = start(ctx, values, 'article')
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    assert start(ctx, values, 'article').data['id'] == response.data['id']
    assert start(ctx, {**values, 'topic_index': 2}, 'article').status_code == 409
    assert task.input['brief']['voice_version_id'] == voice['id']
    assert task.input['topic']['title'] == '选题1'

    def model(*args, **kwargs):
        task.refresh_from_db()
        assert task.stage in ['正在按文风写作', '正在校对个人文风']
        brief = args[2]['brief']
        assert brief['voice_profile']['prompt'] == voice['content']['prompt']
        assert 'production_format' not in brief and 'duration' not in brief
        return {'article': article_content(), 'summary': '表达符合已确认规则，无需修改。'} if task.stage == '正在校对个人文风' else article_content()

    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    execute(*claim(task))
    task.refresh_from_db()
    assert task.stage == 'completed' and task.output['body'] == article_content()['body']
    assert task.output['style_review']['status'] == 'completed'
    assert task.versions.first().content == article_content()
    finish(task)
    url = f'{ctx.root}/tasks/{task.pk}'
    listed = ctx.client.get(url + '/versions')
    assert listed.status_code == 200 and len(listed.data) == 1
    edit = {**article_content(), 'body': '我校正后的正文。'}
    saved = ctx.client.post(url + '/versions', {'revision': 1, 'content': edit}, format='json')
    assert saved.status_code == 201 and saved.data['revision'] == 2
    assert ctx.client.post(url + '/versions', {'revision': 1, 'content': edit}, format='json').status_code == 409
    downloaded = ctx.client.get(url + f"/versions/{saved.data['id']}/download")
    assert downloaded.status_code == 200
    assert '我校正后的正文。' in downloaded.content.decode()
    assert '发布前核对' not in downloaded.content.decode()
    assert ctx.client.get(url).data['output']['creation_context']['voice_version_number'] == 1
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url + '/versions').status_code == 404
    assert ctx.client.post(url + '/versions', {'revision': 2, 'content': edit}, format='json').status_code == 404


def test_article_checks_source_and_target_account(ctx):
    _, _, topics = topics_for(ctx)
    assert start(ctx, {'kind': 'article'}, 'missing').status_code == 400
    assert start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk), 'topic_index': 3}, 'index').status_code == 400
    other = other_account(ctx)
    assert start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk), 'target_account_id': str(other.pk)}, 'wrong-account').status_code == 400
    topics.kind = 'voice_analysis'
    topics.save()
    assert start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk)}, 'wrong-kind').status_code == 400


def test_cancelled_article_does_not_save_model_output(ctx, monkeypatch):
    _, _, topics = topics_for(ctx)
    response = start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk)}, 'article')
    task = m.Task.objects.get(pk=response.data['id'])
    payload, sink = claim(task)
    def model(*args, **kwargs):
        sink.cancelled = True
        return article_content()
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    with pytest.raises(InterruptedError): execute(payload, sink)
    assert not task.versions.exists()


def test_article_survives_source_account_removal(ctx, monkeypatch):
    _, _, topics = topics_for(ctx)
    response = start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk)}, 'article')
    task = m.Task.objects.get(pk=response.data['id'])
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', Mock(return_value=article_content()))
    execute(*claim(task))
    finish(task)
    assert ctx.client.delete(ctx.url).status_code == 204
    task.refresh_from_db()
    assert task.input == {} and task.versions.first().content['body'] == article_content()['body']


@pytest.mark.parametrize('value', [None, {}, {'title': '标题', 'body': ' '}, {'title': '标题', 'body': 'a' * 20001}, {'title': '标题', 'body': '正文', 'notes': '不是数组'}])
def test_article_validator_rejects_invalid_or_empty_results(value):
    with pytest.raises(ValueError): validate_article(value)

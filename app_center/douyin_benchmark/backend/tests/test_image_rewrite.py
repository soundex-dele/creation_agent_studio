from unittest.mock import Mock

import pytest

from .test_douyin import ctx, claim, add_work, post
from ..image_rewrite import writing_instruction, validate_image_rewrite
from ..models import Account, Task, Work
from ... import runtime


def image_work(ctx):
    work = add_work(ctx)
    work.metadata.update(kind='image_album', title='原始标题', description='原始描述')
    work.save()
    return work


@pytest.mark.parametrize('theme', ['', '新的创作主题'])
def test_image_rewrite_uses_skill_without_media_and_restores_frozen_context(ctx, skill, monkeypatch, theme):
    work = image_work(ctx)
    body = {'kind': 'rewrite', 'work_id': str(work.pk), 'source_text': '校正并补充的原文',
            'theme': theme, 'rewrite_requirements': '自然具体'}
    response = post(ctx, body, 'image')
    assert response.status_code == 201, response.data
    task = Task.objects.get(pk=response.data['id'])
    assert post(ctx, body, 'image').data['id'] == str(task.pk)
    assert post(ctx, {**body, 'theme': '另一个主题'}, 'image').status_code == 409
    work.metadata.update(title='后来的标题', description='后来的描述', kind='video')
    work.save()
    context = ctx.client.get(f'{ctx.url}/tasks/{task.pk}').data['copy_context']
    assert context == {'work_title': '原始标题', 'work_description': '原始描述', 'work_kind': 'image_album',
                       'source_task_id': '', 'source_text': body['source_text'], 'theme': theme,
                       'rewrite_requirements': '自然具体'}
    for module, name in [(runtime.media, 'download_video'), (runtime.media, 'extract_audio'),
                         (runtime.media, 'extract'), (runtime, 'transcribe_segments')]:
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError('图文不能调用媒体处理')))
    output = {'text': '# 新文章\n\n完整正文。'}
    # Capture the final instruction entering the structured generation layer.
    model = Mock(return_value=output)
    monkeypatch.setattr(runtime.analysis, 'generate_json', model)
    runtime.execute(*claim(task))
    instruction = model.call_args.kwargs['instruction']
    for expected in ['写作技能正文', '写作资料', '大纲模板', 'theme 非空时以指定主题为准', 'theme 为空时沿用']:
        assert expected in instruction
    assert body['source_text'] in model.call_args.kwargs['content']
    assert not model.call_args.kwargs['image_paths']
    task.refresh_from_db()
    assert task.output == output
    assert task.versions.get().content == output
    task.run.status = 'succeeded'
    task.run.save()
    url = f'{ctx.url}/tasks/{task.pk}'
    saved = ctx.client.post(url + '/versions', {'revision': 1, 'content': {'text': '# 修改标题\n\n修改正文'}}, format='json')
    assert saved.status_code == 201
    assert ctx.client.post(url + '/versions', {'revision': 1, 'content': output}, format='json').status_code == 409
    download = url + f'/versions/{saved.data["id"]}/download'
    assert ctx.client.get(download).content.decode() == '# 修改标题\n\n修改正文'
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url).status_code == 404
    assert ctx.client.get(download).status_code == 404
    assert post(ctx, body, 'reader').status_code == 404


def test_image_input_limits_and_work_isolation(ctx):
    work = image_work(ctx)
    body = {'kind': 'rewrite', 'work_id': str(work.pk), 'source_text': '参考原文'}
    for field, value in [('source_text', ' '), ('source_text', 'x' * 20001), ('theme', 'x' * 2001),
                         ('rewrite_requirements', 'x' * 3001), ('source_task_id', str(ctx.task.pk))]:
        assert post(ctx, {**body, field: value}).status_code == 400
    assert post(ctx, {**body, 'source_text': 'x' * 20000, 'theme': 'x' * 2000,
                      'rewrite_requirements': 'x' * 3000}, 'limits').status_code == 201
    other = Account.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.owner,
                                   source_url='https://www.douyin.com/user/other')
    other_work = Work.objects.create(account=other, platform_id='other', metadata={'kind': 'image_album'})
    assert post(ctx, {**body, 'work_id': str(other_work.pk)}, 'other').status_code == 404
    work.metadata['kind'] = 'video'
    work.save()
    assert post(ctx, body, 'video-no-source').status_code == 400


@pytest.mark.parametrize('failure', ['missing', 'empty', 'encoding', 'escape', 'oversized'])
def test_skill_errors_are_explicit(skill, failure):
    path = skill / 'references/writing.md'
    if failure == 'missing':
        path.unlink()
    elif failure == 'empty':
        path.write_text(' ', encoding='utf-8')
    elif failure == 'encoding':
        path.write_bytes(b'\xff')
    elif failure == 'escape':
        path.write_text('references/../../outside.md', encoding='utf-8')
    else:
        path.write_text('x' * 160001, encoding='utf-8')
    with pytest.raises(ValueError, match='无法加载 wechat-viral-article 技能资料'):
        writing_instruction()


def test_missing_skill_fails_task_without_fallback(ctx, skill, monkeypatch):
    (skill / 'SKILL.md').unlink()
    work = image_work(ctx)
    response = post(ctx, {'kind': 'rewrite', 'work_id': str(work.pk), 'source_text': '参考原文'})
    task = Task.objects.get(pk=response.data['id'])
    model = Mock(side_effect=AssertionError('不得退回普通提示词'))
    monkeypatch.setattr(runtime.analysis, 'call_model', model)
    with pytest.raises(RuntimeError, match='wechat-viral-article'):
        runtime.execute(*claim(task))
    task.refresh_from_db()
    assert 'SKILL.md' in task.error
    assert not task.versions.exists()
    model.assert_not_called()


@pytest.mark.parametrize('text', ['只有正文', '# 只有标题', '# 标题\n\n  '])
def test_article_requires_title_and_body(text):
    with pytest.raises(ValueError):
        validate_image_rewrite({'text': text})

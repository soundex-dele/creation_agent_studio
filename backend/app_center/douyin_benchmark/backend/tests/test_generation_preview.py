import json
from unittest.mock import Mock

import pytest

from ..generation_preview import GenerationPreview
from .. import models as m
from ...runtime import execute
from .test_douyin import ctx, claim  # noqa: F401
from .test_article import topics_for, article_content
from .test_research import start


def test_preview_throttles_replaces_bounds_and_ignores_private_events(monkeypatch):
    clock = [0]
    monkeypatch.setattr('app_center.douyin_benchmark.backend.generation_preview.time.monotonic', lambda: clock[0])
    persist = Mock()
    preview = GenerationPreview(persist, lambda: False)
    preview.on_event('agent.item', {'text': 'private reasoning'})
    preview.on_event('tool.started', {'text': 'private arguments'})
    preview.on_event('output.delta', {'text': None})
    assert persist.call_count == 1
    preview.on_event('output.delta', {'text': '首段'})
    preview.on_event('output.delta', {'text': '尾段'})
    assert persist.call_count == 2
    preview.finish()
    assert persist.call_args.args[0] == {'text': '首段尾段', 'state': 'received'}
    clock[0] = 2
    preview.on_event('output.snapshot', {'text': '替换内容'})
    assert persist.call_args.args[0]['text'] == '替换内容'
    preview.on_event('output.delta', {'text': '字' * 200001})
    preview.finish()
    assert len(persist.call_args.args[0]['text']) == 200000


def article_task(ctx):
    _, _, topics = topics_for(ctx)
    response = start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk)}, 'preview')
    return m.Task.objects.get(pk=response.data['id'])


def test_running_preview_is_private_and_does_not_create_a_version(ctx, monkeypatch):
    task = article_task(ctx)
    payload, sink = claim(task)

    def generate(**kwargs):
        callback = kwargs['on_event']
        callback('output.delta', {'text': '{"body":"正在写'})
        task.refresh_from_db()
        assert task.progress['ai_preview']['text'] == '{"body":"正在写'
        assert task.output == {} and not task.versions.exists()
        response = ctx.client.get(f'{ctx.root}/tasks/{task.pk}')
        assert response.data['progress']['ai_preview']['text'] == '{"body":"正在写'
        ctx.client.force_authenticate(ctx.reader)
        assert ctx.client.get(f'{ctx.root}/tasks/{task.pk}').status_code == 404
        ctx.client.force_authenticate(ctx.owner)
        return article_content()

    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', generate)
    execute(payload, sink)
    task.refresh_from_db()
    assert task.output == article_content() and task.versions.count() == 1
    assert 'ai_preview' not in task.progress
    assert '正在写' not in str(sink.emit.call_args_list)


def test_repair_replaces_preview_instead_of_appending(ctx, monkeypatch):
    task = article_task(ctx)
    attempts = []

    def generate(**kwargs):
        task.refresh_from_db()
        assert task.progress['ai_preview'] == {'text': '', 'state': 'waiting'}
        attempts.append(1)
        value = {'title': '无正文的第一轮'} if len(attempts) == 1 else article_content()
        kwargs['on_event']('output.delta', {'text': json.dumps(value, ensure_ascii=False)})
        return value

    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', generate)
    execute(*claim(task))
    assert len(attempts) == 2 and task.versions.count() == 1


@pytest.mark.parametrize('stop', ['failure', 'cancel', 'lease'])
def test_stopped_generation_never_saves_a_final_article(ctx, monkeypatch, stop):
    from modules.execution.models import RunLease
    from django.utils import timezone
    task = article_task(ctx)
    payload, sink = claim(task)

    def generate(**kwargs):
        callback = kwargs['on_event']
        callback('output.delta', {'text': '已收到的片段'})
        if stop == 'failure':
            callback('output.delta', {'text': '（最后片段）'})
            raise RuntimeError('请求失败')
        if stop == 'cancel':
            sink.cancelled = True
        else:
            RunLease.objects.filter(attempt_id=payload['attempt_id']).update(expires_at=timezone.now())
        callback('output.snapshot', {'text': '迟到的输出'})
        return article_content()

    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', generate)
    with pytest.raises(RuntimeError if stop == 'failure' else InterruptedError):
        execute(payload, sink)
    task.refresh_from_db()
    assert not task.versions.exists() and task.output == {}
    assert task.progress['ai_preview']['text'] == ('已收到的片段（最后片段）' if stop == 'failure' else '已收到的片段')

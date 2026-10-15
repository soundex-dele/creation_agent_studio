from unittest.mock import Mock

import pytest
from core.llm.application import GenerationError
from app_center.project_promotion import runtime
from ..models import AITask, Case
from .test_promotion import ctx, post, get, Sink


def execute(ctx, task, sink=None):
    runtime.execute(dict(run_id=task['run_id'], organization_id=str(ctx['org'].pk), input={'task_id': task['id']}), sink or Sink())


def submit(ctx):
    return post(ctx, 'ai/tasks', dict(kind='case', instruction='真实功能', request_key='errors'), 202)


def capacity():
    return GenerationError('模型服务繁忙，请稍后重试。', code='engine_overloaded', retryable=True)


def test_capacity_retries_same_payload_then_succeeds_without_duplicate_drafts(ctx, monkeypatch):
    task = submit(ctx)
    generate = Mock(side_effect=[capacity(), capacity(), {'title': '演示', 'data': {}}])
    wait = Mock(side_effect=lambda seconds, check: check())
    monkeypatch.setattr(runtime, 'generate_json', generate)
    monkeypatch.setattr(runtime, 'retry_delay', wait)
    execute(ctx, task)
    assert generate.call_count == 3
    assert generate.call_args_list[0] == generate.call_args_list[1] == generate.call_args_list[2]
    assert [c.args[0] for c in wait.call_args_list] == [2, 4]
    result = get(ctx, f"ai/tasks/{task['id']}")
    assert result['status'] == 'succeeded'
    assert Case.objects.count() == 0
    for _ in range(2):
        post(ctx, f"ai/tasks/{task['id']}/apply", {}, 200)
    assert Case.objects.count() == 1


def test_capacity_retry_limit_preserves_specific_error(ctx, monkeypatch):
    task = submit(ctx)
    generate = Mock(side_effect=capacity())
    monkeypatch.setattr(runtime, 'generate_json', generate)
    monkeypatch.setattr(runtime, 'retry_delay', lambda seconds, check: check())
    with pytest.raises(RuntimeError, match='模型服务仍繁忙'):
        execute(ctx, task)
    assert generate.call_count == 3
    row = AITask.objects.get(pk=task['id'])
    assert row.status == 'failed' and row.data['error_code'] == 'engine_overloaded'
    assert '检查模型配置' not in row.error
    assert Case.objects.count() == 0


@pytest.mark.parametrize('error,code', [
    (GenerationError('需要重新登录', code='authentication_failed'), 'authentication_failed'),
    (GenerationError('系统模型生成超时', code='timeout'), 'timeout'),
    (ValueError('raw secret'), 'invalid_json'),
])
def test_nontransient_errors_fail_once_and_do_not_expose_raw_values(ctx, monkeypatch, error, code):
    task = submit(ctx)
    generate = Mock(side_effect=error)
    monkeypatch.setattr(runtime, 'generate_json', generate)
    with pytest.raises(RuntimeError):
        execute(ctx, task)
    assert generate.call_count == 1
    row = AITask.objects.get(pk=task['id'])
    assert row.data['error_code'] == code and 'raw secret' not in row.error


def test_cancel_during_capacity_backoff_prevents_next_call(ctx, monkeypatch):
    task = submit(ctx); sink = Sink()
    generate = Mock(side_effect=capacity())
    monkeypatch.setattr(runtime, 'generate_json', generate)
    def cancel(seconds, check):
        sink.cancelled = True
        check()
    monkeypatch.setattr(runtime, 'retry_delay', cancel)
    execute(ctx, task, sink)
    assert generate.call_count == 1
    assert get(ctx, f"ai/tasks/{task['id']}")['status'] == 'cancelled'
    assert Case.objects.count() == 0


def test_retry_delay_stops_immediately_when_cancelled():
    check = Mock(side_effect=InterruptedError())
    with pytest.raises(InterruptedError):
        runtime.retry_delay(30, check)
    check.assert_called_once()

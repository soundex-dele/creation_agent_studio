from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import OperationalError

from ... import runtime


@pytest.fixture
def progress_context(monkeypatch):
    active = SimpleNamespace(save=Mock())
    sink = SimpleNamespace(emit=Mock())
    transactions = []

    @contextmanager
    def current(payload, sink):
        transactions.append("enter")
        try:
            yield active
        finally:
            transactions.append("exit")

    monkeypatch.setattr(runtime, "current", current)
    monkeypatch.setattr(runtime, "connection", SimpleNamespace(vendor="sqlite"))
    sleep = Mock(side_effect=lambda _: transactions.append("sleep"))
    monkeypatch.setattr(runtime.time, "sleep", sleep)
    return active, sink, transactions, sleep


def test_busy_progress_retries_fresh_transaction_and_emits_once(progress_context):
    active, sink, transactions, sleep = progress_context
    active.save.side_effect = [OperationalError("database is locked"), None]
    runtime.save_task_progress({}, sink, "转写口播", progress={"current": 0, "total": 66})
    assert transactions == ["enter", "exit", "sleep", "enter", "exit"]
    assert active.progress == {"current": 0, "total": 66}
    sink.emit.assert_called_once_with("progress.updated", {"stage": "转写口播", "current": 0, "total": 66})


def test_busy_progress_is_bounded(progress_context):
    active, sink, _, sleep = progress_context
    active.save.side_effect = OperationalError("database is locked")
    with pytest.raises(ValueError, match="数据库繁忙"):
        runtime.save_task_progress({}, sink, "转写口播")
    assert active.save.call_count == 6 and sleep.call_count == 5
    sink.emit.assert_not_called()


def test_other_database_errors_are_not_retried(progress_context):
    active, sink, _, sleep = progress_context
    active.save.side_effect = OperationalError("missing table")
    with pytest.raises(OperationalError):
        runtime.save_task_progress({}, sink, "转写口播")
    sleep.assert_not_called()
    sink.emit.assert_not_called()


def test_retry_rechecks_lease_before_writing(progress_context, monkeypatch):
    active, sink, _, sleep = progress_context

    @contextmanager
    def revoked(payload, sink):
        raise InterruptedError("租约失效")
        yield

    def conflict(**kwargs):
        monkeypatch.setattr(runtime, "current", revoked)
        raise OperationalError("database is locked")

    active.save.side_effect = conflict
    with pytest.raises(InterruptedError):
        runtime.save_task_progress({}, sink, "转写口播")
    assert active.save.call_count == 1
    sink.emit.assert_not_called()

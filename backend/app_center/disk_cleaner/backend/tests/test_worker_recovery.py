from contextlib import nullcontext
from unittest.mock import Mock

from django.db import OperationalError

from ..management.commands import run_disk_cleaner_worker as command


def test_worker_recovers_database_connection_without_resuming_deletion(monkeypatch, tmp_path):
    monkeypatch.setattr(command.fs, "supported", lambda: True)
    monkeypatch.setattr(command.fs, "host_id", lambda: "test-host")
    monkeypatch.setenv("ProgramData", str(tmp_path))
    monkeypatch.setattr(command, "CoordinatorFileLock", lambda path: nullcontext())
    reconcile = Mock()
    monkeypatch.setattr(command, "interrupt_previous", reconcile)
    reconnect = Mock()
    monkeypatch.setattr(command, "close_old_connections", reconnect)
    next_task = Mock(side_effect=[OperationalError("database is locked"), KeyboardInterrupt()])
    monkeypatch.setattr(command, "process_next", next_task)
    monkeypatch.setattr(command.time, "sleep", lambda _: None)
    try:
        command.Command().handle(once=False)
    except KeyboardInterrupt:
        pass
    assert next_task.call_count == 2
    assert reconcile.call_count == 2  # startup, then reconcile interrupted work
    reconnect.assert_called_once()

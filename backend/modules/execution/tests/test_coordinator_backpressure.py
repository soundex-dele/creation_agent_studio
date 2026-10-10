"""A busy output queue must not starve lease renewal or sibling executions."""
import queue
import sqlite3
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from modules.execution.application.runs import create_run
from modules.execution.infrastructure import coordinator as coordinator_module
from modules.execution.infrastructure.claim import claim_next_run
from modules.execution.infrastructure.coordinator import ActiveChild, ExecutionCoordinator
from modules.execution.models import Run


pytestmark = pytest.mark.django_db(transaction=True)
sqlite_only = pytest.mark.skipif(connection.vendor != "sqlite", reason="SQLite contention recovery")


class Messages(queue.Queue):
    def close(self):
        pass


@pytest.fixture
def busy_coordinator(monkeypatch):
    epoch = timezone.now()
    clock = SimpleNamespace(seconds=0.0)
    monkeypatch.setattr(timezone, "now", lambda: epoch + timedelta(seconds=clock.seconds))
    monkeypatch.setattr(coordinator_module, "time", SimpleNamespace(monotonic=lambda: clock.seconds))
    actor = get_user_model().objects.create_user(username="busy-worker-owner")
    organization = actor.owned_organizations.get()
    coordinator = ExecutionCoordinator(worker_id="busy-worker", worker_pool="agent", max_children=2)
    coordinator._next_maintenance_at = float("inf")
    monkeypatch.setattr(coordinator, "_record_usage", lambda *args: None)

    def start(*, count, alive=True):
        run = create_run(
            organization=organization, owner=actor, executor_kind="agent",
            executor_key="agent-completion", source_type="test",
            definition_snapshot={}, input_data={},
        )
        claimed = claim_next_run(worker_id="busy-worker", worker_pool="agent", lease_seconds=30)
        process = MagicMock()
        process.is_alive.return_value = alive
        process.terminate.side_effect = lambda: setattr(process.is_alive, "return_value", False)
        active = ActiveChild(
            claimed=claimed, process=process, messages=Messages(),
            cancel_event=threading.Event(), next_heartbeat_at=clock.seconds + 10,
        )
        for index in range(count):
            active.messages.put({"kind": "event", "type": "agent.tool", "payload": {
                "id": "tool-1", "method": "item/commandExecution/outputDelta",
                "delta": f"{index}\n",
            }})
        active.messages.put({"kind": "terminal", "outcome": "succeeded", "output": {}})
        coordinator._active[claimed.attempt.id] = active
        return run, active

    return coordinator, clock, start


def test_sustained_output_renews_leases_and_services_sibling_runs(busy_coordinator, monkeypatch):
    coordinator, clock, start = busy_coordinator
    children = [start(count=100), start(count=100)]
    handle = coordinator._handle_message

    def slow_persistence(active, message):
        result = handle(active, message)
        clock.seconds += 0.4
        return result

    monkeypatch.setattr(coordinator, "_handle_message", slow_persistence)
    coordinator.tick(allow_claim=False)
    for run, active in children:
        assert 0 < run.events.filter(type="agent.tool").count() < 100
        assert not active.cancel_event.is_set()
    assert clock.seconds < 10

    for _ in range(300):
        if not coordinator.active_count:
            break
        clock.seconds += coordinator.poll_interval
        coordinator.tick(allow_claim=False)

    assert coordinator.active_count == 0
    assert clock.seconds > 30  # Real lease validation spans multiple renewals.
    for run, active in children:
        run.refresh_from_db()
        active.claimed.lease.refresh_from_db()
        assert run.status == Run.Status.SUCCEEDED
        assert run.attempt_count == 1
        assert not active.cancel_event.is_set()
        assert active.claimed.lease.heartbeat_at > active.claimed.lease.acquired_at
        payloads = run.events.filter(type="agent.tool").order_by("sequence").values_list(
            "payload", flat=True,
        )
        assert [payload["delta"] for payload in payloads] == [f"{index}\n" for index in range(100)]


def test_exited_child_drains_bounded_batches_before_processing_terminal(busy_coordinator):
    coordinator, clock, start = busy_coordinator
    run, active = start(count=250, alive=False)

    coordinator.tick(allow_claim=False)
    assert 0 < run.events.filter(type="agent.tool").count() < 250
    for _ in range(10):
        if not coordinator.active_count:
            break
        clock.seconds += 0.3  # Longer than the missing-terminal grace period.
        coordinator.tick(allow_claim=False)

    run.refresh_from_db()
    assert coordinator.active_count == 0
    assert run.status == Run.Status.SUCCEEDED
    assert run.events.filter(type="agent.tool").count() == 250
    assert not active.cancel_event.is_set()


def test_busy_output_does_not_delay_forced_cancellation(busy_coordinator):
    coordinator, _clock, start = busy_coordinator
    run, active = start(count=250)
    Run.objects.filter(pk=run.pk).update(status=Run.Status.CANCELLING)
    coordinator.cancel_grace_seconds = 0

    coordinator.tick(allow_claim=False)

    run.refresh_from_db()
    assert run.status == Run.Status.CANCELLED
    assert 0 < run.events.filter(type="agent.tool").count() < 250
    assert active.cancel_event.is_set()
    active.process.terminate.assert_called_once()
    assert coordinator.active_count == 0


@sqlite_only
def test_locked_heartbeat_defers_child_without_stopping_siblings(busy_coordinator, monkeypatch):
    coordinator, clock, start = busy_coordinator
    run, active = start(count=1)
    sibling, _ = start(count=0)
    renew = coordinator_module.renew_lease
    clock.seconds = 10

    def locked_once(**kwargs):
        if kwargs["lease_token"] == active.claimed.lease.token:
            raise OperationalError("database is locked")
        return renew(**kwargs)

    monkeypatch.setattr(coordinator_module, "renew_lease", locked_once)
    coordinator.tick(allow_claim=False)
    sibling.refresh_from_db()
    assert sibling.status == Run.Status.SUCCEEDED
    assert not active.cancel_event.is_set()
    assert coordinator.active_count == 1
    assert active.next_heartbeat_at == 10

    monkeypatch.setattr(coordinator_module, "renew_lease", renew)
    coordinator.tick(allow_claim=False)
    run.refresh_from_db()
    assert run.status == Run.Status.SUCCEEDED
    assert coordinator.active_count == 0


def test_real_sqlite_writer_lock_recovers_on_next_poll(busy_coordinator):
    if connection.vendor != "sqlite":
        pytest.skip("SQLite writer contention regression")
    coordinator, clock, start = busy_coordinator
    run, active = start(count=1)
    clock.seconds = 10
    blocker = sqlite3.connect(str(connection.settings_dict["NAME"]), uri=True, timeout=0.01)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        coordinator.tick(allow_claim=False)
        assert coordinator.active_count == 1
        assert not active.cancel_event.is_set()
        assert active.next_heartbeat_at == 10
    finally:
        blocker.rollback()
        blocker.close()

    coordinator.tick(allow_claim=False)
    run.refresh_from_db()
    assert run.status == Run.Status.SUCCEEDED
    assert run.attempt_count == 1
    assert not active.cancel_event.is_set()


@pytest.mark.parametrize("kind", ["event", "terminal"])
@sqlite_only
def test_locked_message_rolls_back_and_replays_once_in_order(
    busy_coordinator, monkeypatch, kind,
):
    coordinator, _clock, start = busy_coordinator
    run, active = start(count=2, alive=False)
    handle = coordinator._handle_message
    failed = False

    def lock_after_writes(child, message):
        nonlocal failed
        terminal = handle(child, message)
        if message["kind"] == kind and not failed:
            failed = True
            raise OperationalError("database table is locked")
        return terminal

    monkeypatch.setattr(coordinator, "_handle_message", lock_after_writes)
    coordinator.tick(allow_claim=False)
    run.refresh_from_db()
    assert run.status == Run.Status.RUNNING
    assert active.pending_message["kind"] == kind
    assert not active.cancel_event.is_set()
    assert not run.events.filter(type="run.succeeded").exists()
    coordinator.tick(allow_claim=False)
    run.refresh_from_db()
    assert run.status == Run.Status.SUCCEEDED
    assert active.pending_message is None
    assert coordinator.active_count == 0
    payloads = run.events.filter(type="agent.tool").order_by("sequence").values_list("payload", flat=True)
    assert [payload["delta"] for payload in payloads] == ["0\n", "1\n"]
    assert run.events.filter(type="run.succeeded").count() == 1
    assert run.attempt_count == 1


@sqlite_only
def test_post_commit_lock_does_not_replay_terminal(busy_coordinator, monkeypatch):
    coordinator, _clock, start = busy_coordinator
    run, active = start(count=0, alive=False)
    handle = coordinator._handle_message

    def locked_notification():
        raise OperationalError("database is locked")

    def add_notification(child, message):
        result = handle(child, message)
        transaction.on_commit(locked_notification)
        return result

    monkeypatch.setattr(coordinator, "_handle_message", add_notification)
    coordinator.tick(allow_claim=False)
    assert active.pending_message is None
    assert active.terminal_received
    coordinator.tick(allow_claim=False)
    run.refresh_from_db()
    assert run.status == Run.Status.SUCCEEDED
    assert run.events.filter(type="run.succeeded").count() == 1
    assert not active.cancel_event.is_set()
    assert coordinator.active_count == 0


@sqlite_only
def test_locked_artifact_reuses_object_without_duplicate_rows(busy_coordinator, monkeypatch, settings, tmp_path):
    settings.ARTIFACT_ROOT = tmp_path
    coordinator, _clock, start = busy_coordinator
    run, active = start(count=0)
    terminal = active.messages.get_nowait()
    active.messages.put({"kind": "artifact", "content": b"article", "filename": "result.txt"})
    active.messages.put(terminal)
    handle = coordinator._handle_message

    def locked_after_artifact(child, message):
        result = handle(child, message)
        if message["kind"] == "artifact":
            raise OperationalError("database is locked")
        return result

    monkeypatch.setattr(coordinator, "_handle_message", locked_after_artifact)
    coordinator.tick(allow_claim=False)
    object_key = active.pending_artifact_key
    assert object_key
    assert not run.artifacts.exists()
    monkeypatch.setattr(coordinator, "_handle_message", handle)
    coordinator.tick(allow_claim=False)
    assert run.artifacts.get().object_key == object_key
    assert (tmp_path / object_key).read_bytes() == b"article"
    assert len(list(tmp_path.rglob("*.txt"))) == 1
    assert active.pending_artifact_key is None


@pytest.mark.parametrize("phase", ["maintenance", "claim"])
@sqlite_only
def test_locked_background_work_keeps_active_child_running(busy_coordinator, monkeypatch, phase):
    coordinator, _clock, start = busy_coordinator
    run, active = start(count=0)

    def locked(*args):
        raise OperationalError("database is locked")

    monkeypatch.setattr(coordinator, "_maintain" if phase == "maintenance" else "_claim_available", locked)
    coordinator.tick()
    run.refresh_from_db()
    assert run.status == Run.Status.SUCCEEDED
    assert not coordinator._stopping
    assert not active.cancel_event.is_set()


@pytest.mark.parametrize("cancel", [True, False])
@sqlite_only
def test_deferred_result_still_obeys_cancellation_and_expired_lease(busy_coordinator, monkeypatch, cancel):
    coordinator, clock, start = busy_coordinator
    run, active = start(count=0)
    handle = coordinator._handle_message

    def locked(*args):
        raise OperationalError("database is locked")

    monkeypatch.setattr(coordinator, "_handle_message", locked)
    coordinator.tick(allow_claim=False)
    assert active.pending_message is not None
    if cancel:
        Run.objects.filter(pk=run.pk).update(status=Run.Status.CANCELLING)
    else:
        clock.seconds = 31
    monkeypatch.setattr(coordinator, "_handle_message", handle)
    coordinator.tick(allow_claim=False)
    run.refresh_from_db()
    assert run.status != Run.Status.SUCCEEDED
    assert not run.events.filter(type="run.succeeded").exists()
    assert active.cancel_event.is_set()
    assert coordinator.active_count == 0
    if cancel:
        assert run.status == Run.Status.CANCELLED


@pytest.mark.parametrize("vendor,error", [("sqlite", "disk I/O error"), ("postgresql", "database is locked")])
def test_unrelated_database_errors_are_not_suppressed(busy_coordinator, monkeypatch, vendor, error):
    coordinator, _clock, _start = busy_coordinator
    monkeypatch.setattr(connection, "vendor", vendor)

    def broken(*args):
        raise OperationalError(error)

    monkeypatch.setattr(coordinator, "_maintain", broken)
    with pytest.raises(OperationalError, match=error):
        coordinator.tick()

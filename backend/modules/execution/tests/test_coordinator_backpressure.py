"""A busy output queue must not starve lease renewal or sibling executions."""
import queue
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from modules.execution.application.runs import create_run
from modules.execution.infrastructure import coordinator as coordinator_module
from modules.execution.infrastructure.claim import claim_next_run
from modules.execution.infrastructure.coordinator import ActiveChild, ExecutionCoordinator
from modules.execution.models import Run


pytestmark = pytest.mark.django_db(transaction=True)


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

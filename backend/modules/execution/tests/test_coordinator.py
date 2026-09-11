import queue
import threading

import pytest
from django.contrib.auth import get_user_model

from modules.execution.infrastructure.coordinator import ExecutionCoordinator
from modules.execution.models import Run
from modules.execution.runtime.child import execute_child


def test_child_reports_invalid_adapter_without_database_access():
    messages = queue.Queue()
    execute_child(
        {"input": {}},
        messages,
        threading.Event(),
        "missing.module:execute",
    )

    terminal = messages.get_nowait()
    assert terminal["kind"] == "terminal"
    assert terminal["outcome"] == "failed"
    assert terminal["error_code"] == "execution_adapter_failed"
    assert "Cannot load execution adapter" in terminal["error_message"]


@pytest.mark.django_db(transaction=True)
def test_empty_coordinator_tick_reaps_then_checks_queue(monkeypatch):
    calls = []
    get_user_model().objects.create_user(username="coordinator-owner")

    monkeypatch.setattr(
        "modules.execution.infrastructure.coordinator.reap_expired_leases",
        lambda **kwargs: calls.append(("reap", kwargs)),
    )
    monkeypatch.setattr(
        "modules.execution.infrastructure.coordinator.claim_next_run",
        lambda **kwargs: calls.append(("claim", kwargs)),
    )
    coordinator = ExecutionCoordinator(
        worker_id="test-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
        max_children=1,
        adapter_entries={"test-adapter": "tests.fake:execute"},
    )

    coordinator.run_once()

    assert calls[0] == ("reap", {"limit": 100})
    assert calls[1][0] == "claim"
    assert calls[1][1]["worker_pool"] == Run.ExecutorKind.MEDIA
    assert calls[1][1]["executor_keys"] == ("test-adapter",)


def test_coordinator_with_no_registered_adapters_does_not_claim(monkeypatch):
    monkeypatch.setattr(
        "modules.execution.infrastructure.coordinator.claim_next_run",
        lambda **kwargs: pytest.fail("coordinator must not claim without adapters"),
    )
    coordinator = ExecutionCoordinator(
        worker_id="test-coordinator",
        worker_pool=Run.ExecutorKind.AGENT,
    )

    coordinator._claim_available()

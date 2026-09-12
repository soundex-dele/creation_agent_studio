import multiprocessing
import queue
import threading
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from modules.execution.infrastructure.coordinator import ExecutionCoordinator
from modules.execution.application.runs import create_run
from modules.execution.infrastructure.claim import claim_next_run
from modules.execution.models import Run
from modules.execution.runtime.child import execute_child


def _suspending_adapter(_payload, sink):
    sink.request_input(
        input_kind="answer",
        request_payload={"question": "Continue?"},
        checkpoint={"cursor": 3},
        expires_in_seconds=120,
    )


def _django_model_adapter(_payload, _sink):
    from apps.enterprise.models import Organization

    return {"model": Organization._meta.label}


def test_spawned_child_initializes_django_before_loading_adapter():
    context = multiprocessing.get_context("spawn")
    messages = context.Queue()
    cancel_event = context.Event()
    process = context.Process(
        target=execute_child,
        args=(
            {"input": {}},
            messages,
            cancel_event,
            "modules.execution.tests.test_coordinator:_django_model_adapter",
        ),
    )

    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)

    assert process.exitcode == 0
    terminal = messages.get(timeout=2)
    assert terminal["outcome"] == "succeeded"
    assert terminal["output"] == {"model": "enterprise.Organization"}
    messages.close()


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


def test_child_reports_one_canonical_suspend_message():
    messages = queue.Queue()
    execute_child(
        {"input": {}},
        messages,
        threading.Event(),
        "modules.execution.tests.test_coordinator:_suspending_adapter",
    )

    suspended = messages.get_nowait()
    assert suspended == {
        "kind": "suspend",
        "input_kind": "answer",
        "request_payload": {"question": "Continue?"},
        "checkpoint": {"cursor": 3},
        "expires_in_seconds": 120,
    }
    with pytest.raises(queue.Empty):
        messages.get_nowait()


@pytest.mark.django_db(transaction=True)
def test_coordinator_persists_suspend_as_checkpoint_and_waiting_input():
    actor = get_user_model().objects.create_user(username="suspend-owner")
    organization = actor.owned_organizations.get()
    run = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.AGENT,
        executor_key="agent-completion",
        source_type="agent",
        source_id="1",
        definition_snapshot={},
        input_data={"message": "hello"},
    )
    claimed = claim_next_run(
        worker_id="test-coordinator",
        worker_pool=Run.ExecutorKind.AGENT,
        lease_seconds=30,
        executor_keys=("agent-completion",),
    )
    coordinator = ExecutionCoordinator(
        worker_id="test-coordinator",
        worker_pool=Run.ExecutorKind.AGENT,
        adapter_entries={"agent-completion": "unused:adapter"},
    )

    terminal = coordinator._handle_message(SimpleNamespace(claimed=claimed), {
        "kind": "suspend",
        "input_kind": "answer",
        "request_payload": {"question": "Continue?"},
        "checkpoint": {"messages": [{"role": "user", "content": "hello"}]},
        "expires_in_seconds": 120,
    })

    assert terminal is True
    run.refresh_from_db()
    assert run.status == Run.Status.WAITING_INPUT
    assert run.pending_input_kind == Run.InputKind.ANSWER
    checkpoint = run.artifacts.get(kind="checkpoint")
    assert checkpoint.metadata["checkpoint"]["messages"][0]["content"] == "hello"
    assert list(run.events.values_list("type", flat=True)) == [
        "run.queued", "run.started", "artifact.created", "input.required",
    ]


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

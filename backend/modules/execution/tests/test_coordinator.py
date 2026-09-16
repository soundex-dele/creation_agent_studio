import multiprocessing
import queue
import threading
import hashlib
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from modules.execution.infrastructure.coordinator import (
    ExecutionCoordinator,
    ExecutionCoordinatorSupervisor,
)
from modules.execution.application.commands import submit_run_command
from modules.execution.application.runs import LeaseFence, create_run, finish_attempt
from modules.execution.infrastructure.claim import claim_next_run
from modules.execution.models import Run, RunCommand
from modules.execution.runtime.child import execute_child


def _suspending_adapter(_payload, sink):
    sink.request_input(
        input_kind="answer",
        request_payload={"question": "Continue?"},
        checkpoint={"cursor": 3},
        expires_in_seconds=120,
    )


def _waiting_adapter(_payload, sink):
    sink.wait_for_children(
        child_run_ids=["00000000-0000-0000-0000-000000000001"],
        checkpoint={"layer": 1},
    )


def _django_model_adapter(_payload, _sink):
    from apps.enterprise.models import Organization

    return {"model": Organization._meta.label}


class _FakeCoordinator:
    def __init__(self, active_counts):
        self.active_counts = list(active_counts)
        self.calls = []
        self.stopped = False

    @property
    def active_count(self):
        return self.active_counts[0]

    def tick(self, *, allow_claim=True):
        self.calls.append(allow_claim)
        if len(self.active_counts) > 1:
            self.active_counts.pop(0)

    def stop(self):
        self.stopped = True


def test_supervisor_ticks_all_pools_and_stops_them(monkeypatch):
    first = _FakeCoordinator([1, 1, 0])
    second = _FakeCoordinator([1, 1, 0])
    monkeypatch.setattr(
        "modules.execution.infrastructure.coordinator.time.sleep", lambda _seconds: None
    )
    supervisor = ExecutionCoordinatorSupervisor(
        (first, second), poll_interval=0.01
    )

    supervisor.run_once()
    supervisor.stop()

    assert first.calls == [True, False]
    assert second.calls == [True, False]
    assert first.stopped is True
    assert second.stopped is True


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


def test_child_loads_standard_dotted_adapter_path():
    messages = queue.Queue()
    execute_child(
        {"input": {}},
        messages,
        threading.Event(),
        "modules.execution.tests.test_coordinator._django_model_adapter",
    )

    terminal = messages.get_nowait()
    assert terminal["outcome"] == "succeeded"
    assert terminal["output"] == {"model": "enterprise.Organization"}


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


def test_child_reports_one_canonical_child_wait_message():
    messages = queue.Queue()
    execute_child(
        {"input": {}},
        messages,
        threading.Event(),
        "modules.execution.tests.test_coordinator:_waiting_adapter",
    )

    assert messages.get_nowait() == {
        "kind": "wait_for_children",
        "child_run_ids": ["00000000-0000-0000-0000-000000000001"],
        "checkpoint": {"layer": 1},
    }
    with pytest.raises(queue.Empty):
        messages.get_nowait()


@pytest.mark.django_db(transaction=True)
def test_workflow_releases_worker_and_is_requeued_by_child_completion(settings, tmp_path):
    settings.ARTIFACT_ROOT = tmp_path
    actor = get_user_model().objects.create_user(username="workflow-wait-owner")
    organization = actor.owned_organizations.get()
    root = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        source_id="1",
        definition_snapshot={},
        input_data={},
    )
    child = create_run(
        organization=organization,
        owner=actor,
        parent=root,
        node_key="step",
        executor_kind=Run.ExecutorKind.MEDIA,
        executor_key="batch-transcribe",
        source_type="workflow_step",
        source_id="step",
        definition_snapshot={},
        input_data={},
    )
    claimed_root = claim_next_run(
        worker_id="workflow-coordinator",
        worker_pool=Run.ExecutorKind.WORKFLOW,
        executor_keys=("workflow-dag",),
    )
    coordinator = ExecutionCoordinator(
        worker_id="workflow-coordinator",
        worker_pool=Run.ExecutorKind.WORKFLOW,
        adapter_entries={"workflow-dag": "unused:adapter"},
    )

    terminal = coordinator._handle_message(SimpleNamespace(claimed=claimed_root), {
        "kind": "wait_for_children",
        "child_run_ids": [str(child.id)],
        "checkpoint": {"layer": [str(child.id)]},
    })

    assert terminal is True
    root.refresh_from_db()
    assert root.status == Run.Status.WAITING_CHILDREN
    assert root.current_attempt_id is None

    claimed_child = claim_next_run(
        worker_id="media-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
        executor_keys=("batch-transcribe",),
    )
    finish_attempt(
        run_id=child.id,
        organization_id=organization.id,
        attempt_id=claimed_child.attempt.id,
        lease_fence=LeaseFence(
            token=claimed_child.lease.token,
            epoch=claimed_child.lease.epoch,
        ),
        outcome=Run.Status.SUCCEEDED,
        output_summary={"ok": True},
    )

    root.refresh_from_db()
    assert root.status == Run.Status.QUEUED
    assert root.events.filter(type="run.dependencies_ready").exists()


@pytest.mark.django_db(transaction=True)
def test_coordinator_persists_suspend_as_checkpoint_and_waiting_input(
    settings, tmp_path,
):
    settings.ARTIFACT_ROOT = tmp_path
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
    assert (tmp_path / checkpoint.object_key).read_text() == (
        '{"messages":[{"content":"hello","role":"user"}]}'
    )
    assert list(run.events.values_list("type", flat=True)) == [
        "run.queued", "run.started", "artifact.created", "input.required",
    ]


@pytest.mark.django_db(transaction=True)
def test_coordinator_persists_adapter_artifact_and_metadata(settings, tmp_path):
    settings.ARTIFACT_ROOT = tmp_path
    actor = get_user_model().objects.create_user(username="artifact-owner")
    organization = actor.owned_organizations.get()
    run = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.MEDIA,
        executor_key="batch-transcribe",
        source_type="application",
        source_id="1",
        definition_snapshot={},
        input_data={},
    )
    claimed = claim_next_run(
        worker_id="artifact-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
        lease_seconds=30,
        executor_keys=("batch-transcribe",),
    )
    coordinator = ExecutionCoordinator(
        worker_id="artifact-coordinator",
        worker_pool=Run.ExecutorKind.MEDIA,
        adapter_entries={"batch-transcribe": "unused:adapter"},
    )
    content = b"durable transcript\n"

    terminal = coordinator._handle_message(SimpleNamespace(claimed=claimed), {
        "kind": "artifact",
        "artifact_kind": "transcript",
        "filename": "../unsafe.txt",
        "content": content,
        "mime_type": "text/plain",
        "metadata": {"language": "zh"},
    })

    assert terminal is False
    artifact = run.artifacts.get(kind="transcript")
    assert artifact.content_hash == hashlib.sha256(content).hexdigest()
    assert artifact.size == len(content)
    assert artifact.mime_type == "text/plain"
    assert artifact.metadata == {"language": "zh", "filename": "unsafe.txt"}
    assert (tmp_path / artifact.object_key).read_bytes() == content
    event = run.events.get(type="artifact.created")
    assert event.payload["artifact_id"] == str(artifact.id)
    assert event.payload["content_hash"] == artifact.content_hash


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


@pytest.mark.django_db(transaction=True)
def test_workflow_cancel_cascades_to_running_agent():
    actor = get_user_model().objects.create_user(username="workflow-cancel-owner")
    organization = actor.owned_organizations.get()
    root = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        source_id="1",
        definition_snapshot={},
        input_data={},
    )
    child = create_run(
        organization=organization,
        owner=actor,
        parent=root,
        node_key="writer",
        executor_kind=Run.ExecutorKind.AGENT,
        executor_key="agent-completion",
        source_type="workflow_step",
        source_id="writer",
        definition_snapshot={},
        input_data={},
    )
    claim_next_run(
        worker_id="agent-coordinator",
        worker_pool=Run.ExecutorKind.AGENT,
        executor_keys=("agent-completion",),
    )

    submit_run_command(
        run_id=root.id,
        organization_id=organization.id,
        actor=actor,
        command_type=RunCommand.Type.CANCEL,
        idempotency_key="cancel-workflow-with-agent",
        payload={"reason": "user_requested"},
    )

    root.refresh_from_db()
    child.refresh_from_db()
    assert root.status == Run.Status.CANCELLED
    assert child.status == Run.Status.CANCELLING
    assert child.commands.get(type=RunCommand.Type.CANCEL).payload == {
        "reason": "parent_cancelled"
    }


@pytest.mark.django_db(transaction=True)
def test_coordinator_force_stops_agent_after_cancellation_grace():
    actor = get_user_model().objects.create_user(username="cancelled-agent-owner")
    organization = actor.owned_organizations.get()
    run = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.AGENT,
        executor_key="agent-completion",
        source_type="agent",
        source_id="1",
        definition_snapshot={},
        input_data={"message": "keep working"},
    )
    claimed = claim_next_run(
        worker_id="agent-coordinator",
        worker_pool=Run.ExecutorKind.AGENT,
        executor_keys=("agent-completion",),
    )
    Run.objects.filter(pk=run.pk).update(status=Run.Status.CANCELLING)

    class Process:
        terminated = False

        def is_alive(self):
            return not self.terminated

        def terminate(self):
            self.terminated = True

        def join(self, timeout=None):
            return None

    class Messages:
        def get_nowait(self):
            raise queue.Empty

        def close(self):
            return None

    cancel_event = threading.Event()
    process = Process()
    active = SimpleNamespace(
        claimed=claimed,
        process=process,
        messages=Messages(),
        cancel_event=cancel_event,
        next_heartbeat_at=float("inf"),
        span=None,
        exited_at=None,
        cancel_requested_at=None,
    )
    coordinator = ExecutionCoordinator(
        worker_id="agent-coordinator",
        worker_pool=Run.ExecutorKind.AGENT,
        adapter_entries={"agent-completion": "unused:adapter"},
        cancel_grace_seconds=0,
    )
    coordinator._active[claimed.attempt.id] = active

    coordinator._service_child(claimed.attempt.id, active)

    run.refresh_from_db()
    assert cancel_event.is_set()
    assert process.terminated is True
    assert run.status == Run.Status.CANCELLED
    assert run.current_attempt_id is None
    assert run.events.filter(type="run.cancelled").exists()

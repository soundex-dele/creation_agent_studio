import queue
import threading
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.agent_engine.adapters.codex_interactions import input_request
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed, InputRequestMismatch
from modules.execution.application.reaper import reap_expired_leases, expire_waiting_inputs
from modules.execution.application.runs import create_run
from modules.execution.infrastructure.claim import claim_next_run, renew_lease
from modules.execution.infrastructure.coordinator import ExecutionCoordinator, ActiveChild
from modules.execution.models import Run, RunLease
from modules.execution.runtime.child import ChildEventSink

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def live():
    actor = get_user_model().objects.create_user(username="live-owner")
    organization = actor.owned_organizations.get()
    run = create_run(organization=organization, owner=actor, executor_kind="agent", executor_key="agent-completion",
                     source_type="test", definition_snapshot={}, input_data={})
    claimed = claim_next_run(worker_id="live-worker", worker_pool="agent")
    active = ActiveChild(claimed=claimed, process=MagicMock(), messages=queue.Queue(),
                         cancel_event=threading.Event(), controls=queue.Queue(), next_heartbeat_at=float('inf'))
    coordinator = ExecutionCoordinator(worker_id="live-worker", worker_pool="agent")
    return actor, run, active, coordinator


def prompt(active, coordinator):
    request_id = uuid4()
    message = {"id": 53, "method": "item/commandExecution/requestApproval", "params": {
        "threadId": "thread-1", "turnId": "turn-1", "itemId": "command-1", "command": "pwd",
    }}
    assert coordinator._handle_message(active, {"kind": "live_input", "input_request_id": str(request_id),
                                               "input_kind": "permission", "request_payload": input_request(message)}) is False
    return request_id


def test_live_reply_keeps_attempt_and_reaches_waiting_worker(live):
    actor, run, active, coordinator = live
    sink = ChildEventSink(active.messages, active.cancel_event, active.controls)
    results = []
    worker = threading.Thread(target=lambda: results.append(sink.wait_for_input(input_request({
        "id": 53, "method": "item/commandExecution/requestApproval", "params": {"command": "pwd"},
    }))), daemon=True)
    worker.start()
    message = active.messages.get(timeout=2)
    coordinator._handle_message(active, message)
    run.refresh_from_db()
    assert run.status == "waiting_input"
    assert run.current_attempt_id == active.claimed.attempt.id
    assert renew_lease(lease_token=active.claimed.lease.token, lease_epoch=active.claimed.lease.epoch)
    command, _ = submit_run_command(run_id=run.id, organization_id=run.organization_id, actor=actor,
                                 command_type="grant_permission", idempotency_key="approve-live",
                                 input_request_id=run.pending_input_request_id, payload={"selections": ["accept"]})
    run.refresh_from_db()
    assert run.status == "running"
    assert run.current_attempt_id == active.claimed.attempt.id
    coordinator._service_child(active.claimed.attempt.id, active)
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert results[0]["id"] == str(command.id)
    assert results[0]["input_request_id"] == message["input_request_id"]
    command.refresh_from_db()
    assert command.consumed_at is not None
    assert run.attempt_count == 1


def test_wrong_request_and_invalid_decision_are_rejected(live):
    actor, run, active, coordinator = live
    request_id = prompt(active, coordinator)
    for wrong_id, selection, error in [(uuid4(), "accept", InputRequestMismatch), (request_id, "arbitrary", CommandNotAllowed)]:
        with pytest.raises(error):
            submit_run_command(run_id=run.id, organization_id=run.organization_id, actor=actor,
                               command_type="grant_permission", idempotency_key=str(uuid4()),
                               input_request_id=wrong_id, payload={"selections": [selection]})
    run.refresh_from_db()
    assert run.status == "waiting_input"


def test_lost_worker_fails_pending_input_without_replaying_it(live):
    _, run, active, coordinator = live
    prompt(active, coordinator)
    RunLease.objects.filter(pk=active.claimed.lease.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    reap_expired_leases()
    run.refresh_from_db()
    assert run.status == "failed"
    assert run.pending_input_request_id is None
    assert run.current_attempt_id is None
    assert not run.events.filter(type="run.retry_scheduled").exists()


@pytest.mark.parametrize("expire", [False, True])
def test_cancel_or_expiry_preserves_lease_until_worker_stops(live, expire):
    actor, run, active, coordinator = live
    prompt(active, coordinator)
    if expire:
        Run.objects.filter(pk=run.pk).update(pending_input_expires_at=timezone.now() - timedelta(seconds=1))
        expire_waiting_inputs()
    else:
        submit_run_command(run_id=run.id, organization_id=run.organization_id, actor=actor,
                           command_type="cancel", idempotency_key="cancel-live")
    run.refresh_from_db()
    assert run.status == "cancelling"
    assert run.pending_input_request_id is None
    assert run.current_attempt_id == active.claimed.attempt.id
    coordinator._finish(active, {"outcome": "cancelled"})
    run.refresh_from_db()
    assert run.status == "cancelled"
    assert run.current_attempt_id is None


def test_steering_is_durable_idempotent_and_does_not_queue_another_attempt(live):
    actor, run, active, coordinator = live
    coordinator._handle_message(active, {"kind": "event", "type": "agent.session", "payload": {"can_steer": True}})
    kwargs = dict(run_id=run.id, organization_id=run.organization_id, actor=actor,
                  command_type="steer", idempotency_key="one-steer", payload={"text": "check tests first"})
    first, replayed = submit_run_command(**kwargs)
    repeated, replayed = submit_run_command(**kwargs)
    assert replayed and repeated.id == first.id
    coordinator._service_child(active.claimed.attempt.id, active)
    assert active.controls.get_nowait()["payload"]["text"] == "check tests first"
    assert active.controls.empty()
    run.refresh_from_db()
    assert run.status == "running"
    assert run.attempt_count == 1


def test_steer_arriving_before_prompt_is_preserved_for_same_turn():
    messages, controls = queue.Queue(), queue.Queue()
    sink = ChildEventSink(messages, threading.Event(), controls)
    results = []
    controls.put({"type": "steer", "payload": {"text": "keep this"}})
    worker = threading.Thread(target=lambda: results.append(sink.wait_for_input({})), daemon=True)
    worker.start()
    prompt_message = messages.get(timeout=2)
    controls.put({"type": "answer", "input_request_id": prompt_message["input_request_id"]})
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert results[0]["type"] == "answer"
    assert sink.poll_commands() == [{"type": "steer", "payload": {"text": "keep this"}}]


def test_server_resolution_clears_input_on_same_attempt(live):
    _, run, active, coordinator = live
    request_id = prompt(active, coordinator)
    coordinator._handle_message(active, {"kind": "live_input_resolved", "input_request_id": str(request_id)})
    run.refresh_from_db()
    assert run.status == "running"
    assert run.pending_input_request_id is None
    assert run.current_attempt_id == active.claimed.attempt.id
    assert run.events.filter(type="input.resolved").count() == 1


def test_expired_lease_never_delivers_an_accepted_authorization(live):
    actor, run, active, coordinator = live
    request_id = prompt(active, coordinator)
    command, _ = submit_run_command(run_id=run.id, organization_id=run.organization_id, actor=actor,
                                    command_type='grant_permission', idempotency_key='lease-expired',
                                    input_request_id=request_id, payload={'selections': ['accept']})
    RunLease.objects.filter(pk=active.claimed.lease.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    coordinator._service_child(active.claimed.attempt.id, active)
    assert active.controls.empty()
    command.refresh_from_db()
    assert command.consumed_at is None

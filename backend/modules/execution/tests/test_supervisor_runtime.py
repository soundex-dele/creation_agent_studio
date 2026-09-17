from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed
from modules.execution.application.runs import create_run
from modules.execution.models import Run, RunCommand, RunEvent
from modules.execution.runtime import supervisor
from modules.execution.runtime.supervisor import validate_supervisor_plan


def _snapshot(max_tasks=12):
    return {
        "limits": {
            "max_tasks": max_tasks,
            "max_replans": 3,
            "max_parallelism": 3,
        },
        "team": [
            {"target_type": "agent", "target_id": 11},
            {"target_type": "application", "target_id": 22},
        ],
    }


def _plan():
    return {
        "objective": "交付成品",
        "assumptions": ["素材可用"],
        "tasks": [
            {
                "key": "research",
                "title": "调研",
                "target_type": "agent",
                "target_id": 11,
                "instructions": "完成调研",
                "depends_on": [],
                "expected_output": "调研结论",
                "input": {},
            },
            {
                "key": "render",
                "title": "制作",
                "target_type": "application",
                "target_id": 22,
                "instructions": "制作成品",
                "depends_on": ["research"],
                "expected_output": "成品",
                "input": {"format": "html"},
            },
        ],
        "delivery_criteria": ["可直接交付"],
    }


def test_supervisor_plan_is_normalized_and_versioned():
    result = validate_supervisor_plan(_plan(), _snapshot(), version=3)
    assert result["plan_version"] == 3
    assert result["tasks"][1]["depends_on"] == ["research"]
    assert result["budget"]["max_parallelism"] == 3


@pytest.mark.parametrize("mutation,match", [
    (lambda plan: plan["tasks"][0].update(target_id=999), "outside the allow-list"),
    (lambda plan: plan["tasks"][0].update(depends_on=["render"]), "dependency cycle"),
])
def test_supervisor_plan_rejects_unsafe_graphs(mutation, match):
    plan = _plan()
    mutation(plan)
    with pytest.raises(RuntimeError, match=match):
        validate_supervisor_plan(plan, _snapshot(), version=1)


def test_supervisor_plan_enforces_task_budget():
    with pytest.raises(RuntimeError, match="max_tasks"):
        validate_supervisor_plan(_plan(), _snapshot(max_tasks=1), version=1)


def test_supervisor_first_attempt_proposes_plan_and_suspends(monkeypatch):
    plan = validate_supervisor_plan(_plan(), _snapshot(), version=1)
    monkeypatch.setattr(supervisor, "_generate_plan", lambda *args, **kwargs: plan)

    class Suspended(Exception):
        pass

    class Sink:
        def __init__(self):
            self.events = []
            self.request = None

        def emit(self, event_type, payload):
            self.events.append((event_type, payload))

        def request_input(self, **request):
            self.request = request
            raise Suspended()

    sink = Sink()
    with pytest.raises(Suspended):
        supervisor.execute_supervisor({
            "run_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "definition_snapshot": {**_snapshot(), "team": _snapshot()["team"]},
            "input": {"goal": "交付成品"},
        }, sink)
    assert sink.events == [("supervisor.plan.proposed", plan)]
    assert sink.request["input_kind"] == Run.InputKind.PLAN_APPROVAL
    assert sink.request["checkpoint"]["plan"] == plan


@pytest.mark.django_db(transaction=True)
def test_plan_approval_command_requires_current_plan_version():
    actor = get_user_model().objects.create_user(username="supervisor-owner")
    organization = actor.owned_organizations.get()
    run = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="supervisor",
        source_type="supervisor",
        source_id="1",
        definition_snapshot={},
        input_data={"goal": "test"},
    )
    request_id = uuid4()
    run.status = Run.Status.WAITING_INPUT
    run.pending_input_kind = Run.InputKind.PLAN_APPROVAL
    run.pending_input_request_id = request_id
    run.pending_input_expires_at = timezone.now() + timedelta(hours=1)
    run.next_event_sequence = 2
    run.version = 2
    run.save()
    RunEvent.objects.create(
        organization=organization,
        run=run,
        sequence=2,
        type="supervisor.plan.proposed",
        payload={"plan_version": 4, "tasks": []},
    )

    with pytest.raises(CommandNotAllowed, match="current supervisor plan"):
        submit_run_command(
            run_id=run.id,
            organization_id=organization.id,
            actor=actor,
            command_type=RunCommand.Type.APPROVE_PLAN,
            idempotency_key="stale-plan",
            input_request_id=request_id,
            expected_run_version=2,
            payload={"plan_version": 3},
        )

    command, replayed = submit_run_command(
        run_id=run.id,
        organization_id=organization.id,
        actor=actor,
        command_type=RunCommand.Type.APPROVE_PLAN,
        idempotency_key="current-plan",
        input_request_id=request_id,
        expected_run_version=2,
        payload={"plan_version": 4},
    )
    assert replayed is False
    assert command.result["run_status"] == Run.Status.QUEUED

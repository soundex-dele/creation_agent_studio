import multiprocessing
import queue
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import connections, transaction
from django.utils import timezone

from apps.enterprise.models import Organization
from modules.execution.application.errors import LeaseLost
from modules.execution.application.reaper import (
    expire_waiting_inputs,
    reap_expired_leases,
)
from modules.execution.application.runs import (
    LeaseFence,
    append_event_and_transition,
    fail_attempt,
    finish_attempt,
)
from modules.execution.infrastructure.claim import claim_next_run, renew_lease
from modules.execution.models import Run, RunCommand
from modules.execution.runtime.child import execute_child
from modules.tenancy.database import tenant_database_context


ADAPTER_EVENT_TYPES = {
    "output.delta",
    "output.snapshot",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "progress.updated",
}


@dataclass
class ActiveChild:
    claimed: object
    process: object
    messages: object
    cancel_event: object
    next_heartbeat_at: float
    exited_at: float | None = None


class ExecutionCoordinator:
    """Run leased executions while adapters execute in isolated children.

    SQLite uses one file-locked coordinator. PostgreSQL may run many instances;
    row locking, skip-locked claiming and lease fencing provide coordination.
    """

    def __init__(
        self,
        *,
        worker_id,
        worker_pool,
        max_children=2,
        lease_seconds=30,
        poll_interval=0.25,
        adapter_entries=None,
        process_context=None,
    ):
        if max_children < 1:
            raise ValueError("max_children must be at least one")
        if lease_seconds < 3:
            raise ValueError("lease_seconds must be at least three")
        self.worker_id = worker_id
        self.worker_pool = worker_pool
        self.max_children = max_children
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.adapter_entries = dict(adapter_entries or {})
        self._context = process_context or multiprocessing.get_context("spawn")
        self._active = {}
        self._stopping = False
        self._next_maintenance_at = 0.0

    @property
    def active_count(self):
        return len(self._active)

    def _payload(self, claimed):
        checkpoint = claimed.attempt.checkpoint_artifact
        resume_command = claimed.resume_command
        return {
            "run_id": str(claimed.run.id),
            "attempt_id": str(claimed.attempt.id),
            "organization_id": str(claimed.run.organization_id),
            "executor_key": claimed.run.executor_key,
            "definition_snapshot": claimed.run.definition_snapshot,
            "effective_config": claimed.run.definition_snapshot.get(
                "effective_config", {}
            ),
            "input": claimed.run.input,
            "allowed_roots": list(
                getattr(settings, "APPLICATION_RUNTIME_ALLOWED_ROOTS", [])
            ),
            "checkpoint": (
                {
                    "artifact_id": str(checkpoint.id),
                    "object_key": checkpoint.object_key,
                    "content_hash": checkpoint.content_hash,
                    "mime_type": checkpoint.mime_type,
                    "metadata": checkpoint.metadata,
                }
                if checkpoint is not None
                else None
            ),
            "resume_command": (
                {
                    "id": str(resume_command.id),
                    "type": resume_command.type,
                    "input_request_id": str(resume_command.input_request_id),
                    "payload": resume_command.payload,
                }
                if resume_command is not None
                else None
            ),
        }

    def _start_claimed(self, claimed):
        messages = self._context.Queue(
            maxsize=int(getattr(settings, "EXECUTION_EVENT_QUEUE_SIZE", 1000))
        )
        cancel_event = self._context.Event()
        # A spawned child must never inherit a live SQLite connection.
        connections.close_all()
        process = self._context.Process(
            target=execute_child,
            args=(
                self._payload(claimed),
                messages,
                cancel_event,
                self.adapter_entries[claimed.run.executor_key],
            ),
            name=f"run-{self.worker_pool}-{claimed.run.id}",
        )
        process.start()
        self._active[claimed.attempt.id] = ActiveChild(
            claimed=claimed,
            process=process,
            messages=messages,
            cancel_event=cancel_event,
            next_heartbeat_at=time.monotonic() + self.lease_seconds / 3,
        )

    @staticmethod
    def _fence(active):
        return LeaseFence(
            token=active.claimed.lease.token,
            epoch=active.claimed.lease.epoch,
        )

    def _finish(self, active, message):
        claimed = active.claimed
        fence = self._fence(active)
        outcome = message.get("outcome")
        if outcome == "succeeded":
            output = message.get("output") or {}
            schema = (
                claimed.run.definition_snapshot.get("content", {})
                .get("output_schema", {})
            )
            if schema:
                try:
                    from jsonschema.validators import validator_for
                    validator_type = validator_for(schema)
                    validator_type.check_schema(schema)
                    validator_type(schema).validate(output)
                except Exception as exc:
                    fail_attempt(
                        run_id=claimed.run.id,
                        organization_id=claimed.run.organization_id,
                        attempt_id=claimed.attempt.id,
                        lease_fence=fence,
                        error_code="invalid_executor_output",
                        error_message=str(exc),
                    )
                    return
            run_status = Run.objects.filter(pk=claimed.run.id).values_list(
                "status", flat=True
            ).first()
            terminal = (
                Run.Status.CANCELLED
                if run_status == Run.Status.CANCELLING
                else Run.Status.SUCCEEDED
            )
            with transaction.atomic():
                finish_attempt(
                    run_id=claimed.run.id,
                    organization_id=claimed.run.organization_id,
                    attempt_id=claimed.attempt.id,
                    lease_fence=fence,
                    outcome=terminal,
                    output_summary=output,
                )
                if terminal == Run.Status.SUCCEEDED:
                    from modules.execution.application.projections import project_terminal_run
                    project_terminal_run(claimed.run.id, output)
            self._record_usage(claimed, output, "success")
        elif outcome == "cancelled":
            finish_attempt(
                run_id=claimed.run.id,
                organization_id=claimed.run.organization_id,
                attempt_id=claimed.attempt.id,
                lease_fence=fence,
                outcome=Run.Status.CANCELLED,
                output_summary=message.get("output") or {},
            )
        else:
            fail_attempt(
                run_id=claimed.run.id,
                organization_id=claimed.run.organization_id,
                attempt_id=claimed.attempt.id,
                lease_fence=fence,
                error_code=message.get("error_code") or "child_process_failed",
                error_message=message.get("error_message") or "Execution child failed",
            )
            self._record_usage(claimed, {}, "failed")

    @staticmethod
    def _record_usage(claimed, output, status):
        from apps.enterprise.services import record_usage

        record_usage(
            organization=claimed.run.organization,
            user=claimed.run.owner,
            resource_type="run",
            resource_id=claimed.run.id,
            usage=output.get("usage") or {},
            model=str(output.get("model") or ""),
            status=status,
            metadata={
                "executor_kind": claimed.run.executor_kind,
                "executor_key": claimed.run.executor_key,
            },
        )

    def _handle_message(self, active, message):
        if message.get("kind") == "event":
            if message.get("type") not in ADAPTER_EVENT_TYPES:
                self._finish(
                    active,
                    {
                        "outcome": "failed",
                        "error_code": "invalid_adapter_event",
                        "error_message": (
                            f"Adapter emitted unsupported event {message.get('type')!r}"
                        ),
                    },
                )
                return True
            append_event_and_transition(
                run_id=active.claimed.run.id,
                organization_id=active.claimed.run.organization_id,
                attempt_id=active.claimed.attempt.id,
                lease_fence=self._fence(active),
                event_type=message["type"],
                payload=message.get("payload") or {},
            )
            return False
        if message.get("kind") == "terminal":
            self._finish(active, message)
            return True
        return False

    def _service_child(self, attempt_id, active):
        now_monotonic = time.monotonic()
        if now_monotonic >= active.next_heartbeat_at:
            renewed = renew_lease(
                lease_token=active.claimed.lease.token,
                lease_epoch=active.claimed.lease.epoch,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                active.cancel_event.set()
            active.next_heartbeat_at = now_monotonic + self.lease_seconds / 3

        run_status = Run.objects.filter(pk=active.claimed.run.id).values_list(
            "status", flat=True
        ).first()
        if run_status == Run.Status.CANCELLING:
            active.cancel_event.set()
            RunCommand.objects.filter(
                run_id=active.claimed.run.id,
                type=RunCommand.Type.CANCEL,
                consumed_at__isnull=True,
            ).update(consumed_at=timezone.now())

        terminal = False
        while True:
            try:
                message = active.messages.get_nowait()
            except queue.Empty:
                break
            try:
                terminal = self._handle_message(active, message) or terminal
            except LeaseLost:
                active.cancel_event.set()
                terminal = True
            if terminal:
                break

        if terminal:
            self._remove_child(attempt_id, active)
            return

        if not active.process.is_alive():
            if active.exited_at is None:
                active.exited_at = now_monotonic
            elif now_monotonic - active.exited_at >= 0.2:
                try:
                    self._finish(
                        active,
                        {
                            "outcome": "failed",
                            "error_code": "child_process_exited",
                            "error_message": (
                                f"Execution child exited with code {active.process.exitcode}"
                            ),
                        },
                    )
                except LeaseLost:
                    pass
                self._remove_child(attempt_id, active)

    def _remove_child(self, attempt_id, active):
        active.process.join(timeout=0.2)
        if active.process.is_alive():
            active.process.terminate()
            active.process.join(timeout=1)
        active.messages.close()
        self._active.pop(attempt_id, None)

    def _claim_available(self):
        if not self.adapter_entries:
            return
        organization_ids = list(
            Organization.objects.filter(is_active=True).values_list("id", flat=True)
        )
        made_progress = True
        while made_progress and not self._stopping and self.active_count < self.max_children:
            made_progress = False
            for organization_id in organization_ids:
                if self.active_count >= self.max_children:
                    break
                with tenant_database_context(organization_id):
                    claimed = claim_next_run(
                        worker_id=self.worker_id,
                        worker_pool=self.worker_pool,
                        lease_seconds=self.lease_seconds,
                        executor_keys=tuple(self.adapter_entries),
                    )
                if claimed is None:
                    continue
                made_progress = True
                try:
                    self._start_claimed(claimed)
                except Exception as exc:
                    with tenant_database_context(organization_id):
                        fail_attempt(
                            run_id=claimed.run.id,
                            organization_id=claimed.run.organization_id,
                            attempt_id=claimed.attempt.id,
                            lease_fence=LeaseFence(
                                token=claimed.lease.token,
                                epoch=claimed.lease.epoch,
                            ),
                            error_code="child_process_start_failed",
                            error_message=str(exc),
                        )

    def tick(self, *, allow_claim=True):
        now = time.monotonic()
        if now >= self._next_maintenance_at:
            for organization_id in Organization.objects.filter(
                is_active=True
            ).values_list("id", flat=True):
                with tenant_database_context(organization_id):
                    reap_expired_leases(limit=100)
                    expire_waiting_inputs(limit=100)
            cache.set(f"execution-worker:{self.worker_pool}", self.worker_id, 15)
            self._next_maintenance_at = now + 5
        for attempt_id, active in list(self._active.items()):
            with tenant_database_context(active.claimed.run.organization_id):
                self._service_child(attempt_id, active)
        if allow_claim:
            self._claim_available()

    def run_once(self):
        self.tick(allow_claim=True)
        while self._active:
            time.sleep(self.poll_interval)
            self.tick(allow_claim=False)

    def run_forever(self):
        while not self._stopping:
            self.tick(allow_claim=True)
            time.sleep(self.poll_interval)

    def stop(self):
        self._stopping = True
        active_items = list(self._active.items())
        for _attempt_id, active in active_items:
            active.cancel_event.set()
        for attempt_id, active in active_items:
            active.process.join(timeout=1)
            if active.process.is_alive():
                active.process.terminate()
                active.process.join(timeout=1)
            active.messages.close()
            self._active.pop(attempt_id, None)

import hashlib
import json
import time
from datetime import timedelta

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from modules.execution.models import IdempotencyRecord, Run, RunCommand, RunEvent

from .errors import (
    CommandNotAllowed,
    ConcurrentRunUpdate,
    IdempotencyKeyReused,
    InputRequestExpired,
    InputRequestMismatch,
    OrganizationMismatch,
)
from .runs import _publish_event_notification, sync_run_queue_entry


SUBMIT_RUN_COMMAND_OPERATION = "run.command.submit"


def _command_fingerprint(
    *, run_id, command_type, input_request_id, expected_run_version, payload
):
    document = {
        "run_id": str(run_id),
        "type": command_type,
        "input_request_id": str(input_request_id) if input_request_id else None,
        "expected_run_version": expected_run_version,
        "payload": payload,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _find_replay(*, organization_id, actor_id, command_type, idempotency_key, fingerprint):
    record = IdempotencyRecord.objects.for_organization(organization_id).filter(
        actor_id=actor_id,
        operation=SUBMIT_RUN_COMMAND_OPERATION,
        key=idempotency_key,
    ).first()
    if record is not None:
        if record.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "The idempotency key was already used with a different command"
            )
        command_id = record.response_body.get("command_id")
        if record.status == IdempotencyRecord.Status.COMPLETED and command_id:
            return RunCommand.objects.for_organization(organization_id).get(pk=command_id)

    existing = RunCommand.objects.for_organization(organization_id).filter(
        created_by_id=actor_id,
        type=command_type,
        idempotency_key=idempotency_key,
    ).first()
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise IdempotencyKeyReused(
            "The idempotency key was already used with a different command"
        )
    return existing


def _submit_run_command_once(
    *,
    run_id,
    organization_id,
    actor,
    command_type,
    idempotency_key,
    payload=None,
    input_request_id=None,
    expected_run_version=None,
):
    """Persist a Run command and its immediate projection change atomically."""

    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("idempotency_key must contain between 1 and 160 characters")
    if command_type not in RunCommand.Type.values:
        raise ValueError(f"Unsupported command type: {command_type}")

    payload = payload or {}
    fingerprint = _command_fingerprint(
        run_id=run_id,
        command_type=command_type,
        input_request_id=input_request_id,
        expected_run_version=expected_run_version,
        payload=payload,
    )
    replay = _find_replay(
        organization_id=organization_id,
        actor_id=actor.id,
        command_type=command_type,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    if replay is not None:
        return replay, True

    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if str(run.organization_id) != str(organization_id):
            raise OrganizationMismatch("Run belongs to another organization")

        replay = _find_replay(
            organization_id=organization_id,
            actor_id=actor.id,
            command_type=command_type,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay, True

        if expected_run_version is not None and run.version != expected_run_version:
            raise ConcurrentRunUpdate(
                f"Expected run version {expected_run_version}, found {run.version}"
            )
        now = timezone.now()
        is_cancel = command_type == RunCommand.Type.CANCEL
        if is_cancel:
            if run.status in {Run.Status.SUCCEEDED, Run.Status.FAILED}:
                raise CommandNotAllowed(f"Cannot cancel a {run.status} run")
        else:
            if run.status != Run.Status.WAITING_INPUT:
                raise CommandNotAllowed(
                    "Interactive commands require a waiting-input checkpoint"
                )
            if input_request_id != run.pending_input_request_id:
                raise InputRequestMismatch(
                    "Command does not reference the current input request"
                )
            if (
                run.pending_input_expires_at is not None
                and run.pending_input_expires_at <= now
            ):
                raise InputRequestExpired("The current input request has expired")
            if run.pending_input_kind == Run.InputKind.ANSWER:
                allowed_types = {RunCommand.Type.ANSWER}
            elif run.pending_input_kind == Run.InputKind.PLAN_APPROVAL:
                allowed_types = {
                    RunCommand.Type.APPROVE_PLAN,
                    RunCommand.Type.REVISE_PLAN,
                }
            else:
                allowed_types = {
                    RunCommand.Type.GRANT_PERMISSION,
                    RunCommand.Type.DENY_PERMISSION,
                }
            if command_type not in allowed_types:
                raise CommandNotAllowed(
                    f"Command {command_type} is invalid for {run.pending_input_kind} input"
                )
            if command_type in (
                RunCommand.Type.APPROVE_PLAN,
                RunCommand.Type.REVISE_PLAN,
            ):
                latest_plan = run.events.filter(
                    type="supervisor.plan.proposed"
                ).order_by("-sequence").values_list("payload", flat=True).first()
                expected_plan_version = (latest_plan or {}).get("plan_version")
                if payload.get("plan_version") != expected_plan_version:
                    raise CommandNotAllowed(
                        "Command does not reference the current supervisor plan"
                    )
                if (
                    command_type == RunCommand.Type.REVISE_PLAN
                    and not str(payload.get("feedback") or "").strip()
                ):
                    raise CommandNotAllowed("Plan revision feedback is required")

        idempotency_record = IdempotencyRecord.objects.create(
            organization_id=run.organization_id,
            actor=actor,
            operation=SUBMIT_RUN_COMMAND_OPERATION,
            key=idempotency_key,
            request_fingerprint=fingerprint,
            expires_at=now + timedelta(hours=24),
        )
        command = RunCommand.objects.create(
            organization_id=run.organization_id,
            run=run,
            type=command_type,
            input_request_id=input_request_id,
            expected_run_version=expected_run_version,
            payload=payload,
            created_by=actor,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )

        event = None
        clear_pending_input = False
        if not is_cancel:
            new_status = Run.Status.QUEUED
            event_type = "input.accepted"
            finished_at = None
            clear_pending_input = True
        elif run.status in {
            Run.Status.QUEUED,
            Run.Status.WAITING_INPUT,
            Run.Status.WAITING_CHILDREN,
        }:
            new_status = Run.Status.CANCELLED
            event_type = "run.cancelled"
            finished_at = now
            clear_pending_input = True
        elif run.status == Run.Status.RUNNING:
            new_status = Run.Status.CANCELLING
            event_type = "run.cancelling"
            finished_at = run.finished_at
        else:
            # A repeated cancel with a new key is acknowledged without creating
            # duplicate lifecycle events.
            new_status = run.status
            event_type = None
            finished_at = run.finished_at

        if event_type is not None:
            previous_version = run.version
            next_sequence = run.next_event_sequence + 1
            updates = dict(
                status=new_status,
                version=previous_version + 1,
                next_event_sequence=next_sequence,
                finished_at=finished_at,
            )
            if clear_pending_input:
                updates.update(
                    pending_input_request_id=None,
                    pending_input_kind="",
                    pending_input_expires_at=None,
                )
            updated = Run.objects.filter(pk=run.pk, version=previous_version).update(
                **updates
            )
            if updated != 1:
                raise ConcurrentRunUpdate("Run projection changed concurrently")
            event = RunEvent.objects.create(
                organization_id=run.organization_id,
                run=run,
                attempt_id=run.current_attempt_id,
                sequence=next_sequence,
                type=event_type,
                payload={
                    "command_id": str(command.id),
                    "command_type": command.type,
                    "input_request_id": (
                        str(command.input_request_id)
                        if command.input_request_id
                        else None
                    ),
                    "requested_by": actor.id,
                },
            )
            if event_type == "input.accepted":
                from modules.execution.application.projections import (
                    project_input_accepted,
                )
                project_input_accepted(run.id, event, command)
            run.status = new_status
            run.version = previous_version + 1
            run.next_event_sequence = next_sequence
            run.finished_at = finished_at
            if clear_pending_input:
                run.pending_input_request_id = None
                run.pending_input_kind = ""
                run.pending_input_expires_at = None
            sync_run_queue_entry(run)

        command.result = {
            "accepted": event is not None,
            "run_id": str(run.id),
            "run_status": run.status,
            "run_version": run.version,
        }
        command.save(update_fields=("result",))
        idempotency_record.status = IdempotencyRecord.Status.COMPLETED
        idempotency_record.response_status = 202
        idempotency_record.response_body = {"command_id": str(command.id)}
        idempotency_record.save(
            update_fields=("status", "response_status", "response_body")
        )
        if event is not None:
            transaction.on_commit(
                lambda: _publish_event_notification(run.id, event.sequence)
            )
    if command_type == RunCommand.Type.CANCEL:
        child_ids = Run.objects.filter(
            parent_id=run_id,
            status__in=(
                Run.Status.QUEUED,
                Run.Status.RUNNING,
                Run.Status.WAITING_INPUT,
                Run.Status.WAITING_CHILDREN,
                Run.Status.CANCELLING,
            ),
        ).values_list("id", flat=True)
        for child_id in child_ids:
            submit_run_command(
                run_id=child_id,
                organization_id=organization_id,
                actor=actor,
                command_type=RunCommand.Type.CANCEL,
                idempotency_key=f"cascade-cancel:{run_id}:{child_id}",
                payload={"reason": "parent_cancelled"},
            )
    return command, False


def submit_run_command(
    *,
    run_id,
    organization_id,
    actor,
    command_type,
    idempotency_key,
    payload=None,
    input_request_id=None,
    expected_run_version=None,
    max_retries=4,
):
    """Submit with bounded recovery from SQLite writer contention."""

    for retry_no in range(max_retries):
        try:
            return _submit_run_command_once(
                run_id=run_id,
                organization_id=organization_id,
                actor=actor,
                command_type=command_type,
                idempotency_key=idempotency_key,
                payload=payload,
                input_request_id=input_request_id,
                expected_run_version=expected_run_version,
            )
        except OperationalError as exc:
            is_busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not is_busy or retry_no + 1 >= max_retries:
                raise
        except IntegrityError:
            # A concurrent request can win the idempotency unique constraint
            # between our replay check and insert. A fresh transaction resolves
            # it to either a replay or a key-reuse conflict.
            if retry_no + 1 >= max_retries:
                raise
        time.sleep(0.01 * (2**retry_no))

    raise ConcurrentRunUpdate("Unable to submit command after retries")

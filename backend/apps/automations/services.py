import hashlib
import json
import secrets
import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.enterprise.models import AuditLog, Membership
from modules.catalog.models import ApplicationDeployment
from modules.execution.models import Run

from .models import Automation, AutomationInvocation
from .scheduling import next_fire_time


ACTIVE_RUN_STATUSES = {
    Run.Status.QUEUED,
    Run.Status.RUNNING,
    Run.Status.WAITING_INPUT,
    Run.Status.WAITING_CHILDREN,
    Run.Status.CANCELLING,
}
MAX_PENDING_RUNS = 100


class AutomationValidationError(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


def fingerprint_payload(payload) -> str:
    encoded = json.dumps(
        payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_audit(automation, actor, action, metadata=None):
    AuditLog.objects.create(
        organization=automation.organization,
        actor=actor,
        action=f"automation.{action}",
        resource_type="automation",
        resource_id=str(automation.id),
        metadata=metadata or {},
    )


def validate_target(automation):
    membership = Membership.objects.filter(
        organization=automation.organization,
        user=automation.created_by,
        is_active=True,
    ).first()
    if membership is None:
        raise AutomationValidationError("自动化创建者已不在当前组织，请由管理员接管。")

    if automation.target_type == Automation.TargetType.APPLICATION:
        application = automation.application
        if application is None or not application.is_active:
            raise AutomationValidationError("目标应用不存在或已停用。")
        if application.organization_id not in (None, automation.organization_id):
            raise AutomationValidationError("目标应用不属于当前组织。")
        deployment = ApplicationDeployment.objects.for_organization(
            automation.organization_id
        ).filter(
            application=application,
        ).first()
        if deployment is None:
            raise AutomationValidationError("目标应用尚未激活部署。")
        return application

    if automation.target_type == Automation.TargetType.WORKFLOW:
        from apps.workflows.models import Workflow
        from apps.workflows.views import build_workflow_step_snapshots

        workflow = automation.workflow
        if (
            workflow is None
            or workflow.organization_id != automation.organization_id
            or workflow.execution_mode != Workflow.ExecutionMode.AUTOMATIC
        ):
            raise AutomationValidationError("目标工作流不存在或不是自动执行模式。")
        try:
            build_workflow_step_snapshots(workflow)
        except ValueError as exc:
            raise AutomationValidationError(str(exc)) from exc
        return workflow

    raise AutomationValidationError("旧版 Agent 自动化不再受支持。")


def validate_configuration(automation, *, require_secret=True):
    if not isinstance(automation.default_input, dict):
        raise AutomationValidationError("默认参数必须是 JSON 对象。")
    validate_target(automation)
    if automation.trigger_type == Automation.TriggerType.SCHEDULE:
        automation.next_run_at = next_fire_time(
            kind=automation.schedule_kind,
            expression=automation.schedule,
            run_at=automation.run_at,
            timezone_name=automation.timezone,
        )
    elif automation.trigger_type == Automation.TriggerType.WEBHOOK:
        automation.next_run_at = None
        if require_secret and not automation.secret_digest:
            raise AutomationValidationError("请先生成 Webhook 密钥。")
    else:
        raise AutomationValidationError("平台事件触发不在当前版本支持范围内。")
    return automation


def rotate_secret(automation):
    secret = secrets.token_urlsafe(32)
    automation.secret_digest = make_password(secret)
    automation.secret_prefix = secret[:8]
    automation.secret_rotated_at = timezone.now()
    automation.blocked_reason = ""
    automation.save(update_fields=(
        "secret_digest", "secret_prefix", "secret_rotated_at",
        "blocked_reason", "updated_at",
    ))
    return secret


def verify_secret(automation, secret):
    return bool(secret and automation.secret_digest) and check_password(
        secret, automation.secret_digest
    )


def enable_automation(automation):
    try:
        validate_configuration(automation)
    except AutomationValidationError as exc:
        automation.status = Automation.Status.BLOCKED
        automation.is_active = False
        automation.blocked_reason = str(exc)
        automation.next_run_at = None
        automation.save(update_fields=(
            "status", "is_active", "blocked_reason", "next_run_at", "updated_at",
        ))
        raise
    automation.status = Automation.Status.ACTIVE
    automation.is_active = True
    automation.blocked_reason = ""
    automation.save(update_fields=(
        "status", "is_active", "blocked_reason", "next_run_at", "updated_at",
    ))
    return automation


def disable_automation(automation):
    automation.status = Automation.Status.PAUSED
    automation.is_active = False
    automation.next_run_at = None
    automation.save(update_fields=(
        "status", "is_active", "next_run_at", "updated_at",
    ))
    return automation


def pending_run_count(automation):
    return Run.objects.for_organization(automation.organization_id).filter(
        automation_invocation__automation=automation,
        status__in=ACTIVE_RUN_STATUSES,
    ).count()


def _start_target_run(automation, invocation, payload):
    merged_input = {**dict(automation.default_input or {}), **dict(payload or {})}
    idempotency_key = f"automation:{automation.id}:{invocation.id}"
    if automation.target_type == Automation.TargetType.APPLICATION:
        from modules.execution.application.start_runs import start_application_run

        run, _ = start_application_run(
            organization_id=automation.organization_id,
            application_id=automation.application_id,
            actor=automation.created_by,
            input_data=merged_input,
            priority=0,
            idempotency_key=idempotency_key,
        )
        return run

    from apps.projects.services.workspace_paths import workflow_working_directory
    from apps.workflows.views import build_workflow_step_snapshots
    from modules.execution.application.start_runs import start_workflow_run

    workflow = automation.workflow
    _steps, snapshots = build_workflow_step_snapshots(workflow)
    run, _ = start_workflow_run(
        organization=automation.organization,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        steps=snapshots,
        actor=automation.created_by,
        input_data=merged_input,
        priority=0,
        idempotency_key=idempotency_key,
        output_mapping=workflow.output_mapping,
    )
    run_input = dict(run.input or {})
    run_input["working_directory"] = workflow_working_directory(
        automation.created_by, automation.organization, run.id
    )
    Run.objects.filter(pk=run.pk).update(input=run_input)
    run.input = run_input
    return run


@transaction.atomic
def dispatch_automation(
    automation,
    *,
    source,
    payload=None,
    dedup_key=None,
    scheduled_for=None,
):
    payload = payload or {}
    if not isinstance(payload, dict):
        raise AutomationValidationError("触发载荷必须是 JSON 对象。")
    fingerprint = fingerprint_payload(payload)
    dedup_key = (dedup_key or str(uuid.uuid4()))[:200]
    try:
        # The savepoint keeps the surrounding dispatch transaction usable when
        # a concurrent delivery wins the unique idempotency constraint.
        with transaction.atomic():
            invocation = AutomationInvocation.objects.create(
                organization=automation.organization,
                automation=automation,
                source=source,
                scheduled_for=scheduled_for,
                dedup_key=dedup_key,
                request_fingerprint=fingerprint,
            )
        replayed = False
    except IntegrityError:
        invocation = AutomationInvocation.objects.select_related("run").get(
            automation=automation, dedup_key=dedup_key
        )
        if invocation.request_fingerprint != fingerprint:
            raise IdempotencyConflict(
                "Idempotency-Key 已被不同的请求载荷使用。"
            )
        return invocation, True

    if pending_run_count(automation) >= MAX_PENDING_RUNS:
        invocation.outcome = AutomationInvocation.Outcome.SKIPPED_CAPACITY
        invocation.error = "同一自动化已有 100 个未结束的执行。"
        invocation.save(update_fields=("outcome", "error"))
        return invocation, replayed

    try:
        validate_target(automation)
        run = _start_target_run(automation, invocation, payload)
        invocation.run = run
        invocation.outcome = AutomationInvocation.Outcome.DISPATCHED
        invocation.save(update_fields=("run", "outcome"))
        Automation.objects.filter(pk=automation.pk).update(
            last_triggered_at=timezone.now()
        )
    except AutomationValidationError as exc:
        automation.status = Automation.Status.BLOCKED
        automation.is_active = False
        automation.next_run_at = None
        automation.blocked_reason = str(exc)
        automation.save(update_fields=(
            "status", "is_active", "next_run_at", "blocked_reason", "updated_at",
        ))
        invocation.outcome = AutomationInvocation.Outcome.FAILED
        invocation.error = str(exc)
        invocation.save(update_fields=("outcome", "error"))
    except Exception as exc:
        invocation.outcome = AutomationInvocation.Outcome.FAILED
        invocation.error = str(exc)
        invocation.save(update_fields=("outcome", "error"))
    return invocation, replayed

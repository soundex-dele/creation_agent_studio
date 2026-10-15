"""Public execution capability; implementation remains platform-owned."""
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed, DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from modules.execution.application.start_runs import start_application_run

from modules.execution.runtime.child import _SuspendExecution as SuspendExecution


def get_run(run_id, organization_id):
    """Read the executing task's platform identity without exposing a manager."""
    from modules.execution.models import Run
    return Run.objects.select_related("owner").get(pk=run_id, organization_id=organization_id)


def active_run(payload, sink):
    """Lock and validate an active attempt inside the caller's transaction."""
    from django.utils import timezone
    from modules.execution.models import Run, RunLease
    run = Run.objects.select_for_update().filter(
        pk=payload["run_id"], organization_id=payload["organization_id"],
        status="running", current_attempt_id=payload["attempt_id"],
    ).first()
    if sink.cancelled or not run or not RunLease.objects.filter(
        attempt_id=payload["attempt_id"], released_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists():
        raise InterruptedError("任务已取消或执行租约已失效。")
    return run

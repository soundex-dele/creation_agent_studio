"""Public execution capability; implementation remains platform-owned."""


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


def cancel_run(run, user, reason, *, idempotency_key=None):
    """Cancel through the durable command plane; tolerate a concurrent completion."""
    from modules.execution.application.commands import submit_run_command
    from modules.execution.application.errors import CommandNotAllowed
    from modules.execution.models import RunCommand
    if run and run.status not in {'succeeded', 'failed', 'cancelled', 'cancelling'}:
        try:
            submit_run_command(run_id=run.id, organization_id=run.organization_id, actor=user,
                               command_type=RunCommand.Type.CANCEL,
                               idempotency_key=idempotency_key or f'cancel:{run.id}',
                               payload={'reason': reason})
        except CommandNotAllowed:
            run.refresh_from_db()
            if run.status not in {'succeeded', 'failed', 'cancelled'}:
                raise


_EXPORTS = {'CommandNotAllowed': ('modules.execution.application.errors', 'CommandNotAllowed'),
 'DeploymentUnavailable': ('modules.execution.application.errors', 'DeploymentUnavailable'),
 'IdempotencyKeyReused': ('modules.execution.application.errors', 'IdempotencyKeyReused'),
 'IdempotencyRecord': ('modules.execution.models', 'IdempotencyRecord'),
 'InvalidExecutionDefinition': ('modules.execution.application.errors',
                                'InvalidExecutionDefinition'),
 'Run': ('modules.execution.models', 'Run'),
 'RunArtifact': ('modules.execution.models', 'RunArtifact'),
 'RunArtifactSerializer': ('modules.execution.api.serializers', 'RunArtifactSerializer'),
 'RunCommand': ('modules.execution.models', 'RunCommand'),
 'RunLease': ('modules.execution.models', 'RunLease'),
 'RunSerializer': ('modules.execution.api.serializers', 'RunSerializer'),
 'SuspendExecution': ('modules.execution.runtime.child', '_SuspendExecution'),
 'create_run': ('modules.execution.application.runs', 'create_run'),
 'start_agent_run': ('modules.execution.application.start_runs', 'start_agent_run'),
 'start_application_run': ('modules.execution.application.start_runs', 'start_application_run'),
 'submit_run_command': ('modules.execution.application.commands', 'submit_run_command')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

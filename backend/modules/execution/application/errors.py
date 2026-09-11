class ExecutionError(Exception):
    """Base class for stable execution-domain failures."""

    code = "execution_error"


class InvalidRunTransition(ExecutionError):
    code = "invalid_run_transition"


class ConcurrentRunUpdate(ExecutionError):
    code = "concurrent_run_update"


class LeaseLost(ExecutionError):
    code = "lease_lost"


class OrganizationMismatch(ExecutionError):
    code = "organization_mismatch"


class CommandNotAllowed(ExecutionError):
    code = "command_not_allowed"


class InputRequestMismatch(CommandNotAllowed):
    code = "input_request_mismatch"


class InputRequestExpired(CommandNotAllowed):
    code = "input_request_expired"


class IdempotencyKeyReused(ExecutionError):
    code = "idempotency_key_reused"


class DeploymentUnavailable(ExecutionError):
    code = "deployment_unavailable"


class InvalidExecutionDefinition(ExecutionError):
    code = "invalid_execution_definition"

from django.core.exceptions import ValidationError


class CatalogError(Exception):
    code = "catalog_error"


class DraftVersionConflict(ValidationError):
    problem_code = "draft_version_conflict"

    def __init__(self, message):
        super().__init__(message, code=self.problem_code)


class CatalogInvariantViolation(ValidationError):
    problem_code = "catalog_invariant_violation"

    def __init__(self, message):
        super().__init__(message, code=self.problem_code)


class InvalidApplicationDefinition(ValidationError):
    problem_code = "invalid_application_definition"

    def __init__(self, message, *, errors=None):
        self.definition_errors = errors or []
        super().__init__(message, code=self.problem_code)


class DeploymentVersionConflict(CatalogError):
    code = "deployment_version_conflict"


class InvalidDeploymentRevision(CatalogError):
    code = "invalid_deployment_revision"


class DeploymentRollbackUnavailable(CatalogError):
    code = "deployment_rollback_unavailable"


class QualityGateNotPassed(CatalogError):
    code = "quality_gate_not_passed"

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_attempts: int = Field(default=3, ge=1, le=100)
    retry_safe: bool = True


class ApplicationDefinition(BaseModel):
    """Portable execution contract for an Application Revision."""

    model_config = ConfigDict(extra="allow", strict=True)

    executor_kind: Literal["agent", "media", "workflow", "evaluation"]
    executor_key: str = Field(min_length=1, max_length=160)
    executor_protocol_version: int = Field(default=1, ge=1)
    renderer_key: str | None = Field(default=None, min_length=1, max_length=160)
    renderer_schema_version: int = Field(default=1, ge=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("executor_key", "renderer_key")
    @classmethod
    def validate_registry_key(cls, value):
        if value is not None and not value.strip():
            raise ValueError("registry key must not be blank")
        return value


def validate_application_definition(content, *, schema_version=1):
    if schema_version != 1:
        raise ValueError(f"Unsupported Application definition schema version: {schema_version}")
    return ApplicationDefinition.model_validate(content)


def application_definition_errors(exc: ValidationError):
    errors = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"])
        errors.append(
            {
                "field": location or "content",
                "code": error["type"],
                "message": error["msg"],
            }
        )
    return errors

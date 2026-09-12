from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_attempts: int = Field(default=3, ge=1, le=100)
    retry_safe: bool = True


class AgentBindingDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: int = Field(gt=0)
    label: str = ""
    is_default: bool = False
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    order: int = Field(default=0, ge=0)


class SkillBindingDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill_id: str = Field(min_length=1)
    mode: Literal["required", "default", "optional"] = "default"
    config: dict[str, Any] = Field(default_factory=dict)
    order: int = Field(default=0, ge=0)


class GuidedOptionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str | None = None
    value: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = ""
    icon: str = ""
    order: int = Field(default=0, ge=0)


class GuidedQuestionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str | None = None
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    help_text: str = ""
    type: Literal["text", "single_choice", "multi_choice", "number", "file"]
    placeholder: str = ""
    required: bool = False
    default_value: Any = None
    validation: dict[str, Any] = Field(default_factory=dict)
    order: int = Field(default=0, ge=0)
    options: list[GuidedOptionDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def choices_have_options(self):
        if self.type in ("single_choice", "multi_choice") and not self.options:
            raise ValueError("choice questions require at least one option")
        return self


class GuidedPromptDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str | None = None
    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    icon: str = ""
    prompt_template: str
    action: Literal["fill", "preview", "send"] = "preview"
    is_featured: bool = False
    order: int = Field(default=0, ge=0)
    questions: list[GuidedQuestionDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def prompt_references_known_questions(self):
        import re
        placeholders = set(re.findall(r"\{([a-zA-Z][a-zA-Z0-9_-]*)\}", self.prompt_template))
        keys = {question.key for question in self.questions}
        unknown = placeholders - keys
        if unknown:
            raise ValueError(
                "prompt_template references unknown questions: "
                + ", ".join(sorted(unknown))
            )
        return self


class ChatProfileDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    welcome_message: str = ""
    input_placeholder: str = ""
    empty_state_title: str = ""
    allow_agent_selection: bool = False
    allow_skill_selection: bool = True
    allow_extra_skills: bool = False
    conversation_policy: Literal[
        "new_each_open", "resume_last", "choose_history"
    ] = "choose_history"
    starter_layout: Literal["cards", "list", "compact"] = "cards"


class ApplicationDefinition(BaseModel):
    """Portable execution contract for a non-chat Application Revision."""
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["task", "custom"] = "custom"
    executor_kind: Literal["agent", "media", "workflow", "evaluation"]
    executor_key: str = Field(min_length=1, max_length=160)
    executor_protocol_version: int = Field(default=1, ge=1)
    renderer_key: str | None = Field(default=None, min_length=1, max_length=160)
    renderer_schema_version: int = Field(default=1, ge=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    dependencies: dict[str, list[dict[str, Any]]] = Field(
        default_factory=lambda: {"agents": [], "skills": []}
    )

    @field_validator("executor_key", "renderer_key")
    @classmethod
    def validate_registry_key(cls, value):
        if value is not None and not value.strip():
            raise ValueError("registry key must not be blank")
        return value


class ChatApplicationDefinition(BaseModel):
    """Chat-only revision contract; these fields never exist on base apps."""
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["chat"]
    executor_kind: Literal["agent"] = "agent"
    executor_key: str = Field(min_length=1, max_length=160)
    executor_protocol_version: int = Field(default=1, ge=1)
    renderer_key: Literal["chat"] = "chat"
    renderer_schema_version: int = Field(default=1, ge=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    chat_profile: ChatProfileDefinition = Field(default_factory=ChatProfileDefinition)
    agent_bindings: list[AgentBindingDefinition]
    skill_bindings: list[SkillBindingDefinition] = Field(default_factory=list)
    guided_prompts: list[GuidedPromptDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_chat_references(self):
        if not self.agent_bindings:
            raise ValueError("chat applications require at least one agent binding")
        agent_ids = [binding.agent_id for binding in self.agent_bindings]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("agent bindings must be unique")
        if sum(binding.is_default for binding in self.agent_bindings) != 1:
            raise ValueError("chat applications require exactly one default agent")
        skill_ids = [binding.skill_id for binding in self.skill_bindings]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("skill bindings must be unique")
        prompt_keys = [prompt.key for prompt in self.guided_prompts]
        if len(prompt_keys) != len(set(prompt_keys)):
            raise ValueError("guided prompt keys must be unique")
        entry_key = self.default_config.get("guided_entry_prompt_key")
        if entry_key and entry_key not in set(prompt_keys):
            raise ValueError("guided_entry_prompt_key does not reference a guided prompt")
        return self


def validate_application_definition(content, *, schema_version=1):
    if schema_version != 1:
        raise ValueError(f"Unsupported Application definition schema version: {schema_version}")
    if content.get("kind") == "chat":
        return ChatApplicationDefinition.model_validate(content)
    return ApplicationDefinition.model_validate(content)


def application_definition_errors(exc: ValidationError):
    errors = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"])
        errors.append({
            "field": location or "content",
            "code": error["type"],
            "message": error["msg"],
        })
    return errors

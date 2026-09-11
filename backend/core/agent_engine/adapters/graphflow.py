"""GraphFlow implementation of the agent adapter contract."""
from __future__ import annotations

from typing import Optional

from django.conf import settings

from ..messages import format_messages_for_query
from ..models import LLMResponse, TokenUsage
from ..sdk_loader import load_sdk
from .base import AgentAdapter

_ASK_USER_SCHEMA_GUIDANCE = """
When calling AskUserQuestion, pass one flat JSON object with: question (string),
header (short string), options (2-4 objects with label and description), and
multi_select (boolean). Do not wrap the object in a questions array.
""".strip()


def build_config(
    *,
    system_prompt: str = "",
    working_directory: str = "",
    enable_permissions: Optional[bool] = None,
    provider_override: Optional[dict] = None,
):
    sdk = load_sdk()
    guarded_system_prompt = f"{system_prompt}\n\n{_ASK_USER_SCHEMA_GUIDANCE}".strip()
    effective_permissions = (
        settings.GRAPHFLOW_ENABLE_PERMISSIONS
        if enable_permissions is None
        else enable_permissions
    )
    provider_override = provider_override or {}
    return sdk.EngineConfig(
        default_provider=provider_override.get("provider") or settings.GRAPHFLOW_PROVIDER,
        llm_model=provider_override.get("model") or settings.GRAPHFLOW_MODEL,
        llm_base_url=provider_override.get("base_url") or settings.GRAPHFLOW_BASE_URL,
        workflow_config_file=settings.GRAPHFLOW_WORKFLOW_PATH,
        enable_streaming=settings.GRAPHFLOW_ENABLE_STREAMING,
        enable_permissions=effective_permissions,
        enable_skills=settings.GRAPHFLOW_ENABLE_SKILLS,
        skills_directory=settings.GRAPHFLOW_SKILLS_DIRECTORY,
        system_prompt=guarded_system_prompt,
        working_directory=working_directory,
        max_turns=settings.GRAPHFLOW_MAX_TURNS,
        timeout_seconds=settings.GRAPHFLOW_TIMEOUT_SECONDS,
        fake_provider=settings.GRAPHFLOW_PROVIDER == "fake",
    )


class GraphFlowAdapter(AgentAdapter):
    name = "graphflow"

    def __init__(self, *, api_key=None, base_url=None, model=None, **_options) -> None:
        self.api_key = api_key or settings.GRAPHFLOW_API_KEY
        self.base_url = base_url or settings.GRAPHFLOW_BASE_URL
        self.model = model or settings.GRAPHFLOW_MODEL
        self.content_mode = "snapshot" if settings.GRAPHFLOW_PROVIDER == "anthropic" else "delta"

    def complete(self, messages: list[dict], **options) -> LLMResponse:
        sdk = load_sdk()
        system_prompt, query = format_messages_for_query(messages)
        config = build_config(
            system_prompt=system_prompt,
            working_directory=options.get("working_directory", ""),
            provider_override=options.get("provider_override"),
        )
        with sdk.Engine(
            config,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
        ) as engine:
            result = engine.query(query)
        return LLMResponse(
            content=result.final_answer,
            usage=TokenUsage(
                prompt_tokens=result.token_usage.prompt_tokens,
                completion_tokens=result.token_usage.completion_tokens,
                total_tokens=result.token_usage.total_tokens,
            ),
            model=self.model,
            success=result.success,
            error=result.error_message or None,
        )

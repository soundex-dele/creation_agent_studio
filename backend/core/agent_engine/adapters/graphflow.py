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


def _message_value(message, name, default=""):
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _graphflow_event_bridge(callback, *, content_mode="delta"):
    """Map GraphFlow SDK messages to the durable Run event vocabulary."""

    pending_tools = []

    def emit(event_type, payload):
        if callback is not None:
            callback(event_type, payload)

    def on_message(message):
        message_type = str(_message_value(message, "type"))
        content = str(_message_value(message, "content") or "")
        if message_type == "progress":
            subtype = str(_message_value(message, "subtype") or "content")
            if subtype == "content" and content:
                event_type = (
                    "output.snapshot" if content_mode == "snapshot" else "output.delta"
                )
                emit(event_type, {"text": content})
            elif content:
                emit("progress.updated", {"category": subtype, "message": content})
            return
        if message_type == "tool_use":
            tool_call_id = str(
                _message_value(message, "tool_use_id") or f"tool-{len(pending_tools) + 1}"
            )
            tool_name = str(_message_value(message, "tool_name") or "tool")
            pending_tools.append((tool_call_id, tool_name))
            emit("tool.started", {
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "input": content,
            })
            return
        if message_type == "tool_result":
            tool_call_id = str(_message_value(message, "tool_use_id") or "")
            tool_name = str(_message_value(message, "tool_name") or "")
            if pending_tools:
                pending_id, pending_name = pending_tools.pop(0)
                tool_call_id = tool_call_id or pending_id
                tool_name = tool_name or pending_name
            failed = bool(_message_value(message, "is_error", False))
            payload = {
                "tool_call_id": tool_call_id or "tool-result",
                "name": tool_name or "tool",
                "result": content,
            }
            error_message = str(_message_value(message, "error_message") or "")
            if error_message:
                payload["error_message"] = error_message
            emit("tool.failed" if failed else "tool.completed", payload)

    return on_message


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
            enable_permissions=(
                True if options.get("require_tool_approval") else None
            ),
            provider_override=options.get("provider_override"),
        )
        with sdk.Engine(
            config,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
        ) as engine:
            on_event = options.get("on_event")
            if on_event is not None:
                engine.on_message(_graphflow_event_bridge(
                    on_event,
                    content_mode=self.content_mode,
                ))
            selected_skills = [
                str(item.get("name") or "").strip()
                for item in options.get("skills") or []
                if isinstance(item, dict) and item.get("name")
            ]
            skill_markers = " ".join(f"${name}" for name in selected_skills)
            result = engine.query(f"{skill_markers} {query}".strip())
        input_request = getattr(result, "input_request", None)
        if input_request is None:
            input_request = getattr(result, "pending_question", None)
        if hasattr(input_request, "model_dump"):
            input_request = input_request.model_dump()
        if input_request is not None and not isinstance(input_request, dict):
            input_request = {"question": str(input_request)}
        if input_request:
            input_request = {
                "input_kind": input_request.get("input_kind", "answer"),
                "kind": input_request.get("kind", "question"),
                "header": input_request.get("header", "Agent 提问"),
                "question": input_request.get(
                    "question", "请提供继续执行所需的信息"
                ),
                "options": input_request.get("options", []),
            }
        return LLMResponse(
            content=getattr(result, "final_answer", ""),
            usage=TokenUsage(
                prompt_tokens=result.token_usage.prompt_tokens,
                completion_tokens=result.token_usage.completion_tokens,
                total_tokens=result.token_usage.total_tokens,
            ),
            model=self.model,
            success=bool(getattr(result, "success", False)) or bool(input_request),
            error=getattr(result, "error_message", "") or None,
            input_request=input_request,
        )

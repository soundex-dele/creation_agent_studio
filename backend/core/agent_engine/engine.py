"""Backend-neutral facade used by the durable Agent Run adapter."""
from __future__ import annotations

import logging

from .adapters import AgentAdapter, get_agent_adapter
from .models import LLMResponse

logger = logging.getLogger(__name__)


class AgentEngine:
    """Dispatch a completion to the configured provider adapter."""

    def __init__(
        self,
        config=None,
        *,
        api_key=None,
        base_url=None,
        model=None,
        adapter_name: str = "",
        adapter: AgentAdapter | None = None,
        working_directory: str = "",
    ) -> None:
        self._config = config
        self._working_directory = working_directory
        self._adapter = adapter or get_agent_adapter(
            adapter_name,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        logger.info(
            "AgentEngine initialized adapter=%s config=%r",
            self._adapter.name,
            config,
        )

    def complete(self, messages: list[dict], **options) -> LLMResponse:
        logger.info("AgentEngine.complete called, messages=%d", len(messages))
        response = self._adapter.complete(
            messages,
            working_directory=self._working_directory,
            **options,
        )
        logger.info(
            "AgentEngine.complete finished adapter=%s success=%s tokens=%s error=%r",
            self._adapter.name,
            response.success,
            response.usage.total_tokens,
            response.error,
        )
        return response

    @property
    def adapter_name(self) -> str:
        return self._adapter.name

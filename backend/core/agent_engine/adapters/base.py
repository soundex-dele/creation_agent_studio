"""Stable contracts shared by all agent runtime implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from ..models import LLMResponse


class AgentAdapter(ABC):
    """Adapter implemented by every durable Agent completion backend."""

    name: str
    content_mode = "delta"

    @abstractmethod
    def complete(self, messages: list[dict], **options) -> LLMResponse:
        """Run one completion and return the normalized result."""

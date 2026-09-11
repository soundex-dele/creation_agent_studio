"""Built-in and extension-facing agent adapters."""
from .base import AgentAdapter
from .registry import (
    adapter_registry,
    get_agent_adapter,
    register_agent_adapter,
)


def _register_builtins() -> None:
    from .codex import CodexAdapter
    from .graphflow import GraphFlowAdapter

    register_agent_adapter("graphflow", GraphFlowAdapter)
    register_agent_adapter("codex", CodexAdapter)


_register_builtins()

__all__ = [
    "AgentAdapter",
    "adapter_registry",
    "get_agent_adapter",
    "register_agent_adapter",
]

"""Tool framework base classes.

Following claw_agent_engine's ToolManager pattern:
- BaseTool: Abstract base for all tools
- ToolResult: Standardized result container
- ToolManager: Registration and execution manager
"""

from __future__ import annotations

import json
import logging
from core.observability import operation
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolParameter:
    """Schema for a single tool parameter (JSON Schema compatible)."""

    name: str
    type: str = "string"  # string, number, integer, boolean, object, array
    description: str = ""
    required: bool = True
    enum: list[str] | None = None
    default: Any = None

    def to_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.enum is not None:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class ToolResult:
    """Standardized tool execution result.

    Mirrors claw_agent_engine's ToolResult pattern — success flag with
    optional content (text/json) or error message.
    """

    success: bool = True
    content: str = ""
    is_error: bool = False

    # For structured results (e.g. file listings, search results)
    structured: dict[str, Any] | list[Any] | None = None

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(success=False, content=message, is_error=True)

    @classmethod
    def success(cls, content: str, structured: Any = None) -> ToolResult:
        return cls(success=True, content=content, structured=structured)

    def to_api_format(self) -> dict[str, Any]:
        """Convert to LLM API tool_result format."""
        result: dict[str, Any] = {
            "type": "tool_result",
            "content": self.content,
            "success": self.success,
        }
        if self.structured is not None:
            result["structured"] = self.structured
        return result


class BaseTool(ABC):
    """Abstract base class for all tools.

    Subclasses must implement:
    - name: unique tool identifier
    - description: human-readable description
    - parameters: input parameter schema
    - execute: the actual tool logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name (e.g. 'read_file', 'search_files')."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        """List of input parameters with their schema."""

    def parameters_to_schema(self) -> dict[str, Any]:
        """Convert parameters to JSON Schema format."""
        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = param.to_schema()
            if param.required:
                required.append(param.name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_api_tool(self) -> dict[str, Any]:
        """Convert to LLM API tool definition format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters_to_schema(),
        }

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters.

        Args:
            **kwargs: Parameters matching the declared schema.

        Returns:
            ToolResult with success/error status and content.
        """

    def __repr__(self) -> str:
        return f"<Tool: {self.name}>"


class ToolManager:
    """Manages tool registration, listing, and execution.

    Following claw_agent_engine's ToolManager pattern:
    - register(): Add tools to the registry
    - list_tools(): Get all registered tool info
    - execute(): Run a tool by name
    - has_tool(): Check if a tool is registered
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance.

        Args:
            tool: Tool instance to register.
        """
        self._tools[tool.name] = tool

    def register_factory(self, name: str, factory: Callable[[], BaseTool]) -> None:
        """Register a tool factory for lazy instantiation.

        Args:
            name: Tool name.
            factory: Callable that returns a tool instance.
        """
        self._tools[name] = _LazyTool(factory)

    def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name.
            **kwargs: Parameters to pass to the tool.

        Returns:
            ToolResult from the tool execution.

        Raises:
            ValueError: If tool is not registered.
        """
        tool = self._tools.get(name)
        if tool is None:
            logging.getLogger(__name__).warning("tool.execute state=unknown_tool")
            return ToolResult.error(f"Unknown tool: {name}")
        try:
            with operation(type(tool).__name__, logger=logging.getLogger(__name__)):
                result = tool.execute(**kwargs)
                logging.getLogger(__name__).log(
                    logging.INFO if result.success else logging.ERROR,
                    "tool.execute state=returned success=%s", result.success)
                return result
        except Exception as exc:
            return ToolResult.error(f"Tool '{name}' execution failed: {exc}")

    def list_tools(self) -> list[ToolInfo]:
        """Get information about all registered tools.

        Returns:
            List of ToolInfo for each registered tool.
        """
        return [
            ToolInfo(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters_to_schema(),
            )
            for tool in self._tools.values()
        ]

    def list_api_tools(self) -> list[dict[str, Any]]:
        """Get API tool definitions for all registered tools.

        Returns:
            List of tool definitions in LLM API format.
        """
        return [tool.to_api_tool() for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered.

        Args:
            name: Tool name.

        Returns:
            True if the tool is registered.
        """
        return name in self._tools

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            Tool instance or None.
        """
        return self._tools.get(name)


@dataclass
class ToolInfo:
    """Information about a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any]


class _LazyTool(BaseTool):
    """Wrapper for lazy tool instantiation via factory."""

    def __init__(self, factory: Callable[[], BaseTool]) -> None:
        self._factory = factory
        self._tool: BaseTool | None = None

    def _get_tool(self) -> BaseTool:
        if self._tool is None:
            self._tool = self._factory()
        return self._tool

    @property
    def name(self) -> str:
        return self._get_tool().name

    @property
    def description(self) -> str:
        return self._get_tool().description

    @property
    def parameters(self) -> list[ToolParameter]:
        return self._get_tool().parameters

    def execute(self, **kwargs) -> ToolResult:
        return self._get_tool().execute(**kwargs)

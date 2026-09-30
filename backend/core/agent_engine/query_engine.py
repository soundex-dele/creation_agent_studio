"""Query engine — multi-turn tool calling loop.

Following claw_agent_engine's CallbackQueryEngine pattern:
- submit_query: Main entry point that runs the tool-use loop
- Tool calls are parsed, permissions checked, executed, and results fed back
- Messages are streamed via callback during execution
"""

from __future__ import annotations

import json
import re
from core.observability import log_operation
from typing import TYPE_CHECKING, Any, Callable

from .permissions.manager import PermissionDecision, PermissionManager
from .tools.base import ToolManager, ToolResult

if TYPE_CHECKING:
    from .provider import LLMProvider
    from .system_prompt import SystemPromptBuilder


# Type for streaming callback
MessageCallback = Callable[[dict[str, Any]], None]
PermissionCallback = Callable[[str, str], PermissionDecision]


class QueryResult:
    """Result from a query execution."""

    def __init__(
        self,
        content: str = "",
        success: bool = True,
        error: str = "",
        tool_calls: int = 0,
        usage: Any = None,
    ) -> None:
        self.content = content
        self.success = success
        self.error = error
        self.tool_calls = tool_calls
        self.usage = usage

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "success": self.success,
            "error": self.error,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
        }


class QueryEngine:
    """Multi-turn tool calling loop.

    Following claw_agent_engine's CallbackQueryEngine pattern:
    1. Send messages to LLM with tool definitions
    2. Parse tool_use content blocks
    3. Check permissions for each tool call
    4. Execute tools and collect results
    5. Feed results back to LLM (next turn)
    6. Repeat until no more tool_use blocks or max turns reached
    """

    def __init__(
        self,
        tool_manager: ToolManager,
        permission_manager: PermissionManager,
        max_turns: int = 25,
        max_context_messages: int = 50,
    ) -> None:
        self._tool_manager = tool_manager
        self._permission_manager = permission_manager
        self._max_turns = max_turns
        self._max_context_messages = max_context_messages

    @log_operation
    def submit_query(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        system_prompt_builder: SystemPromptBuilder,
        on_message: MessageCallback | None = None,
        on_permission: PermissionCallback | None = None,
    ) -> QueryResult:
        """Submit a query and execute the tool-use loop.

        Args:
            messages: Message list (mutated in-place as history).
            provider: LLM provider for completions.
            system_prompt_builder: System prompt builder with tool definitions.
            on_message: Optional callback for streaming updates.
            on_permission: Optional callback for permission checks.

        Returns:
            QueryResult with final content and metadata.
        """
        # Update tool definitions in system prompt
        tool_defs = self._tool_manager.list_api_tools()
        system_prompt_builder.set_tool_definitions(tool_defs)
        system_prompt = system_prompt_builder.build()

        # Ensure system message is first
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Trim messages if too long
        self._trim_messages(messages)

        tool_call_count = 0

        for turn in range(self._max_turns):
            # Notify about current turn
            if on_message:
                on_message({
                    "type": "turn",
                    "turn": turn + 1,
                    "max_turns": self._max_turns,
                })

            # Call LLM with current messages
            response = provider.complete(messages)

            if not response.success:
                return QueryResult(
                    success=False,
                    error=f"LLM request failed on turn {turn + 1}: {response.error}",
                    tool_calls=tool_call_count,
                )

            content = response.content.strip()

            # Check if LLM wants to use tools
            tool_uses = self._parse_tool_uses(content)

            if not tool_uses:
                # No more tool calls — LLM provided final answer
                if on_message:
                    on_message({
                        "type": "assistant_message",
                        "content": content,
                    })
                return QueryResult(
                    content=content,
                    success=True,
                    tool_calls=tool_call_count,
                    usage=response.usage,
                )

            # Execute tool calls
            tool_results = []
            for tool_use in tool_uses:
                tool_name = tool_use.get("name", "")
                tool_input = tool_use.get("input", {})

                if on_message:
                    on_message({
                        "type": "tool_use",
                        "name": tool_name,
                        "input": tool_input,
                    })

                # Check permissions
                permission_decision = self._check_permission(
                    tool_name,
                    json.dumps(tool_input, ensure_ascii=False),
                    on_permission,
                )

                if permission_decision.behavior == "deny":
                    result = ToolResult.error(
                        f"Permission denied: {permission_decision.reason}"
                    )
                elif permission_decision.behavior == "ask":
                    # For now, treat 'ask' as 'allow' — in a UI context,
                    # the callback could pause execution for user input
                    result = self._tool_manager.execute(tool_name, **tool_input)
                else:
                    result = self._tool_manager.execute(tool_name, **tool_input)

                tool_call_count += 1
                tool_results.append({
                    "tool_name": tool_name,
                    "result": result,
                })

                if on_message:
                    on_message({
                        "type": "tool_result",
                        "name": tool_name,
                        "success": result.success,
                        "content": result.content[:200],
                    })

            # Build tool result message for next turn
            result_text = self._format_tool_results(tool_results)
            messages.append({"role": "user", "content": result_text})

        # Max turns reached without final answer
        return QueryResult(
            content="Maximum turns reached without completion.",
            success=False,
            error=f"Exceeded maximum of {self._max_turns} turns",
            tool_calls=tool_call_count,
        )

    def _check_permission(
        self,
        tool_name: str,
        tool_input: str,
        callback: PermissionCallback | None,
    ) -> PermissionDecision:
        """Check permission for a tool execution.

        Uses the callback if provided, otherwise uses PermissionManager.
        """
        if callback:
            return callback(tool_name, tool_input)
        return self._permission_manager.check(tool_name, tool_input)

    def _parse_tool_uses(self, content: str) -> list[dict[str, Any]]:
        """Parse tool_use blocks from LLM response content.

        Supports multiple formats:
        - JSON array: [{"name": "read_file", "input": {"path": "..."}}]
        - XML-like: <tool_use name="read_file">{"path": "..."}</tool_use>
        - Claude format: tool_use content blocks in JSON
        """
        tool_uses = []

        # Try JSON array format
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "name" in item:
                        tool_uses.append({
                            "name": item["name"],
                            "input": item.get("input", {}),
                        })
                if tool_uses:
                    return tool_uses
        except (json.JSONDecodeError, TypeError):
            pass

        # Try XML-like format
        pattern = r'<tool_use\s+name="([^"]+)">(.*?)</tool_use>'
        for match in re.finditer(pattern, content, re.DOTALL):
            name = match.group(1)
            input_str = match.group(2).strip()
            try:
                tool_input = json.loads(input_str)
            except json.JSONDecodeError:
                tool_input = {"text": input_str}
            tool_uses.append({"name": name, "input": tool_input})

        # Try Claude-style: look for tool_use in JSON structure
        # This is a simplified version — full implementation would parse
        # the complete API response structure
        if not tool_uses:
            # Look for inline tool use hints: e.g., "I'll use read_file with path=..."
            hint_pattern = r'(?:use|using|calling)\s+(\w+)(?:\s+with\s+(.*))?'
            for match in re.finditer(hint_pattern, content, re.IGNORECASE):
                name = match.group(1)
                if self._tool_manager.has_tool(name):
                    input_str = match.group(2) or ""
                    tool_uses.append({
                        "name": name,
                        "input": self._parse_input_string(input_str),
                    })

        return tool_uses

    def _parse_input_string(self, text: str) -> dict[str, Any]:
        """Parse input string into key-value dict."""
        result = {}
        # Try JSON first
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try key=value pairs
        for match in re.finditer(r'(\w+)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))', text):
            key = match.group(1)
            value = match.group(2) or match.group(3) or match.group(4) or ""
            result[key] = value
        return result

    def _format_tool_results(self, results: list[dict[str, Any]]) -> str:
        """Format tool execution results as a message for the LLM."""
        parts = ["Tool execution results:"]
        for item in results:
            name = item["tool_name"]
            result = item["result"]
            if result.success:
                parts.append(f"\n[{name}]: {result.content[:500]}")
            else:
                parts.append(f"\n[{name}] ERROR: {result.content[:500]}")
        return "\n".join(parts)

    def _trim_messages(self, messages: list[dict[str, Any]]) -> None:
        """Trim messages to max_context_messages, keeping system message."""
        if len(messages) <= self._max_context_messages:
            return

        # Keep system message and last N messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        keep = self._max_context_messages - len(system_msgs)

        messages.clear()
        messages.extend(system_msgs)
        messages.extend(non_system[-keep:])

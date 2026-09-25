"""Tool labels remain specific across streaming events and saved messages."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from apps.conversations.serializers import MessageSerializer
from core.agent_engine.adapters.codex import _codex_tool_payload, _consume_codex_turn
from core.agent_engine.tool_display import normalize_tool_metadata, tool_display_name


class ToolDisplayTest(TestCase):
    def test_uses_structured_command_actions(self):
        for action_type, expected in (
            ("read", "read"), ("search", "search"), ("listFiles", "list"),
            ("unknown", "shell"),
        ):
            with self.subTest(action_type=action_type):
                payload = _codex_tool_payload({
                    "id": "call-1", "type": "commandExecution",
                    "command": "provider command",
                    "commandActions": [{"type": action_type}],
                })
                self.assertEqual(payload["name"], expected)
                self.assertEqual(payload["input"], "provider command")
                self.assertEqual(payload["tool_type"], "commandExecution")

    def test_combines_distinct_actions_without_losing_unknown_operations(self):
        self.assertEqual(tool_display_name("shell", command_actions=[
            {"type": "read"}, {"type": "search"}, {"type": "read"},
        ]), "read / search")
        self.assertEqual(tool_display_name("shell", command_actions=[
            {"type": "read"}, {"type": "unknown"},
        ]), "shell")

    def test_recognizes_simple_legacy_commands_and_shell_wrappers(self):
        for command, expected in (
            ("cat README.md", "read"),
            ("head -n 20 README.md", "read"),
            ("sed -n '1,240p' app.py", "read"),
            ('/bin/zsh -lc "cat README.md"', "read"),
            ("rg -n 'tool' src", "search"),
            ("grep -n tool app.py", "search"),
            ("rg --files src", "list"),
            ("ls -la", "list"),
            ("npm run build", "shell"),
            ("pwd", "shell"),
            ("cat input > output", "shell"),
            ("cat input; npm test", "shell"),
            ("cat input && npm test", "shell"),
            ("cat input\nnpm test", "shell"),
            ("cat input | python script.py", "shell"),
            ('cat "$(python script.py)"', "shell"),
            ("sed -n '1,240p' -i app.py", "shell"),
            ("rg --pre=script.py pattern", "shell"),
            ("cat 'unterminated", "shell"),
            (None, "shell"),
        ):
            with self.subTest(command=command):
                self.assertEqual(tool_display_name("shell", command), expected)

    def test_native_edit_and_concrete_tools_preserve_details(self):
        changes = [{"path": "app.py", "kind": {"type": "update"}, "diff": "+hi"}]
        payload = _codex_tool_payload({
            "id": "edit-1", "type": "fileChange", "changes": changes,
        })
        self.assertEqual(payload["name"], "edit")
        self.assertEqual(payload["input"], changes)
        for item, expected in (
            ({"type": "dynamicToolCall", "tool": "read_file"}, "read_file"),
            ({"type": "mcpToolCall", "server": "fs", "tool": "read"}, "fs.read"),
            ({"type": "webSearch", "query": "docs"}, "web_search"),
        ):
            self.assertEqual(_codex_tool_payload(item)["name"], expected)

    def test_lifecycle_uses_the_same_specific_name(self):
        for item in (
            {"id": "read-1", "type": "commandExecution", "command": "cat app.py",
             "commandActions": [{"type": "read"}]},
            {"id": "edit-1", "type": "fileChange", "changes": [{"path": "app.py"}]},
        ):
            with self.subTest(item=item["type"]):
                thread = MagicMock()
                thread.turn.return_value.stream.return_value = iter([
                    {"method": "item/started", "payload": {"item": item}},
                    {"method": "item/completed", "payload": {
                        "item": {**item, "status": "completed"},
                    }},
                    {"method": "turn/completed", "payload": {
                        "turn": {"status": "completed"},
                    }},
                ])
                events = []
                _consume_codex_turn(thread, "hi", on_event=lambda kind, payload: events.append((kind, payload)))
                self.assertEqual([kind for kind, _ in events], ["tool.started", "tool.completed"])
                expected = "read" if item["type"] == "commandExecution" else "edit"
                self.assertEqual([payload["name"] for _, payload in events], [expected, expected])
                self.assertEqual([payload["tool_call_id"] for _, payload in events], [item["id"]] * 2)

    def test_history_serialization_labels_legacy_calls_without_mutation(self):
        metadata = {
            "agent": {"loaded_skills": ["audit"], "tool_calls": [
                {"id": "1", "name": "shell", "input": "cat README.md", "status": "completed", "result": "hello"},
                {"id": "2", "name": "file_change", "input": "diff", "status": "failed", "error_message": "denied"},
                {"id": "3", "name": "custom_tool", "status": "running"},
            ]},
            "graphflow": {"tool_calls": [{"name": "read_file"}]},
            "other": {"keep": True},
        }
        original = deepcopy(metadata)
        message = SimpleNamespace(
            id=1, run_id=None, role="assistant", content="done",
            metadata=metadata, attachments=[], created_at=datetime.now(timezone.utc),
        )
        result = MessageSerializer(message).data["metadata"]
        expected = deepcopy(metadata)
        expected["agent"]["tool_calls"][0]["name"] = "read"
        expected["agent"]["tool_calls"][1]["name"] = "edit"
        self.assertEqual(result, expected)
        self.assertEqual(metadata, original)

    def test_missing_history_is_unchanged(self):
        for metadata in (None, {}, {"agent": {}}, {"agent": {"tool_calls": None}}):
            self.assertEqual(normalize_tool_metadata(metadata), metadata)

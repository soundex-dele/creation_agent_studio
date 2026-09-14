"""Tests for adapter registration and the Codex event bridge."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch

from django.test import override_settings

from core.agent_engine.adapters.base import AgentAdapter
from core.agent_engine.adapters.codex import (
    CodexAdapter,
    _consume_codex_turn,
    load_codex_sdk,
    resolve_codex_binary,
)
from core.agent_engine.adapters.graphflow import (
    GraphFlowAdapter,
    _graphflow_event_bridge,
    build_config,
)
from core.agent_engine.adapters.registry import AdapterRegistry
from core.agent_engine.models import LLMResponse, TokenUsage


class StubAdapter(AgentAdapter):
    name = "stub"

    def __init__(self, **options):
        self.options = options

    def complete(self, messages, **options):
        return LLMResponse(content="ok", usage=TokenUsage(), model="stub")


class AdapterRegistryTest(TestCase):
    def test_custom_adapter_can_be_registered_and_constructed(self):
        registry = AdapterRegistry()
        registry.register("custom", StubAdapter)

        adapter = registry.create("CUSTOM", marker=3)

        self.assertEqual(adapter.name, "stub")
        self.assertEqual(adapter.options, {"marker": 3})


class GraphFlowIntegrationTest(TestCase):
    @override_settings(
        GRAPHFLOW_PROVIDER="openai",
        GRAPHFLOW_MODEL="deepseek-chat",
        GRAPHFLOW_BASE_URL="https://api.deepseek.com/v1",
        GRAPHFLOW_ENABLE_STREAMING=True,
    )
    @patch("core.agent_engine.adapters.graphflow.load_sdk")
    def test_blank_provider_overrides_fall_back_to_global_settings(self, load_sdk):
        config = build_config(provider_override={
            "provider": "",
            "model": "",
            "base_url": "",
        })

        self.assertEqual(config, load_sdk.return_value.EngineConfig.return_value)
        kwargs = load_sdk.return_value.EngineConfig.call_args.kwargs
        self.assertEqual(kwargs["default_provider"], "openai")
        self.assertEqual(kwargs["llm_model"], "deepseek-chat")
        self.assertEqual(kwargs["llm_base_url"], "https://api.deepseek.com/v1")
        self.assertTrue(kwargs["enable_streaming"])

    def test_maps_content_and_tool_callbacks_to_run_events(self):
        events = []
        bridge = _graphflow_event_bridge(
            lambda event_type, payload: events.append((event_type, payload))
        )

        bridge(SimpleNamespace(type="progress", subtype="content", content="Hi"))
        bridge(SimpleNamespace(
            type="tool_use", tool_use_id="call-1", tool_name="read_file",
            content='{"path":"a.txt"}',
        ))
        bridge(SimpleNamespace(
            type="tool_result", tool_use_id="", tool_name="", content="contents",
            is_error=False, error_message="",
        ))

        self.assertEqual(events, [
            ("output.delta", {"text": "Hi"}),
            ("tool.started", {
                "tool_call_id": "call-1",
                "name": "read_file",
                "input": '{"path":"a.txt"}',
            }),
            ("tool.completed", {
                "tool_call_id": "call-1",
                "name": "read_file",
                "result": "contents",
            }),
        ])

    @override_settings(
        GRAPHFLOW_PROVIDER="openai",
        GRAPHFLOW_MODEL="deepseek-chat",
        GRAPHFLOW_BASE_URL="https://example.com/v1",
    )
    @patch("core.agent_engine.adapters.graphflow.load_sdk")
    def test_registers_streaming_callback_before_query(self, load_sdk):
        sdk = load_sdk.return_value
        engine = sdk.Engine.return_value.__enter__.return_value
        result = SimpleNamespace(
            final_answer="hello",
            token_usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=2, total_tokens=3,
            ),
            success=True,
            error_message="",
            input_request=None,
            pending_question=None,
        )
        engine.query.return_value = result
        callback = MagicMock()

        GraphFlowAdapter().complete(
            [{"role": "user", "content": "hi"}], on_event=callback
        )

        engine.on_message.assert_called_once()
        self.assertEqual(
            [method_call[0] for method_call in engine.method_calls[:2]],
            ["on_message", "query"],
        )


class CodexIntegrationTest(TestCase):
    def test_streams_agent_deltas_and_tool_lifecycle(self):
        notifications = [
            SimpleNamespace(
                method="item/started",
                payload=SimpleNamespace(item=SimpleNamespace(
                    id="call-1", type="commandExecution", command="pwd",
                    status="inProgress",
                )),
            ),
            SimpleNamespace(
                method="item/agentMessage/delta",
                payload=SimpleNamespace(delta="Hello "),
            ),
            SimpleNamespace(
                method="item/agentMessage/delta",
                payload=SimpleNamespace(delta="world"),
            ),
            SimpleNamespace(
                method="item/completed",
                payload=SimpleNamespace(item=SimpleNamespace(
                    id="call-1", type="commandExecution", command="pwd",
                    aggregatedOutput="E:/workspace", status="completed",
                )),
            ),
            SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(turn=SimpleNamespace(
                    status="completed", error=None,
                )),
            ),
        ]
        turn = MagicMock()
        turn.stream.return_value = iter(notifications)
        thread = MagicMock()
        thread.turn.return_value = turn
        events = []

        result = _consume_codex_turn(
            thread,
            "hi",
            on_event=lambda event_type, payload: events.append((event_type, payload)),
        )

        self.assertEqual(result.final_response, "Hello world")
        self.assertEqual([event[0] for event in events], [
            "tool.started", "output.delta", "output.delta", "tool.completed",
        ])
        self.assertEqual(events[0][1], {
            "tool_call_id": "call-1",
            "name": "shell",
            "tool_type": "commandExecution",
            "input": "pwd",
        })
        self.assertEqual(events[-1][1]["result"], "E:/workspace")

    @override_settings(CODEX_SDK_PATH="D:/missing-codex-sdk")
    def test_python_sdk_transport_reports_missing_opt_in_dependency(self):
        load_codex_sdk.cache_clear()
        with self.assertRaisesRegex(RuntimeError, "Codex Python SDK not found"):
            load_codex_sdk()

    @override_settings(
        CODEX_TRANSPORT="app-server",
        CODEX_WORKING_DIRECTORY="D:/workspace",
        CODEX_MODEL="",
    )
    @patch("core.agent_engine.adapters.codex.load_codex_sdk")
    @patch("core.agent_engine.adapters.codex.resolve_codex_binary")
    @patch("core.agent_engine.adapters.codex._AppServerCodex")
    def test_app_server_is_default_and_does_not_load_python_sdk(
        self, app_server, resolve_binary, load_sdk
    ):
        binary = Path("D:/installed/codex.exe")
        resolve_binary.return_value = binary

        sdk, client = CodexAdapter()._client(cwd="D:/project")

        self.assertEqual(sdk.ApprovalMode.deny_all, "deny_all")
        self.assertEqual(client, app_server.return_value)
        app_server.assert_called_once_with(
            codex_bin=binary,
            cwd="D:/project",
            approval_decision="",
        )
        load_sdk.assert_not_called()

    @override_settings(
        CODEX_BINARY="",
        CODEX_REPOSITORY_PATH="D:/workspace/codex",
    )
    def test_resolves_source_build_or_installed_codex(self):
        path = resolve_codex_binary()
        self.assertTrue(path.is_file())
        self.assertTrue(path.name.lower().startswith("codex"))

    @skipUnless(sys.platform == "win32", "Windows standalone install layout")
    @override_settings(CODEX_BINARY="", CODEX_REPOSITORY_PATH="D:/missing-codex")
    def test_resolves_windows_standalone_install_without_path(self):
        with TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "OpenAI" / "Codex" / "bin" / "version" / "codex.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}),
                patch("core.agent_engine.adapters.codex.shutil.which", return_value=None),
            ):
                resolved = resolve_codex_binary()

        self.assertEqual(resolved, binary.resolve())

"""Tests for adapter registration and the Codex event bridge."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch

from django.test import override_settings

from core.agent_engine.adapters.base import AgentAdapter
from core.agent_engine.adapters.codex import (
    CodexAdapter,
    load_codex_sdk,
    resolve_codex_binary,
)
from core.agent_engine.adapters.graphflow import build_config
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
    def test_blank_provider_overrides_fall_back_to_global_settings(self):
        config = build_config(provider_override={
            "provider": "",
            "model": "",
            "base_url": "",
        })

        payload = config.to_dict()
        self.assertEqual(payload["openai"]["model"], "deepseek-chat")
        self.assertEqual(payload["llm"]["provider"], "openai")
        self.assertEqual(payload["llm"]["base_url"], "https://api.deepseek.com/v1")
        self.assertTrue(payload["llm"]["streaming"])


class CodexIntegrationTest(TestCase):
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
        self.assertEqual(path.name.lower(), "codex.exe")

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

"""Tests for the Agent engine and its sole durable Run adapter."""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.test.utils import override_settings

from apps.users.models import User
from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm.factory import build_agent_engine
from apps.agents.execution import execute_agent_completion


class BuildAgentEngineTest(TestCase):
    @override_settings(GRAPHFLOW_API_KEY="key-123", GRAPHFLOW_BASE_URL="https://example.com/v1")
    def test_builds_engine_from_settings(self):
        self.assertIsNotNone(build_agent_engine())


class DurableAgentAdapterTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.organization = self.user.owned_organizations.get()

    @staticmethod
    def _payload(organization_id):
        return {
            "organization_id": str(organization_id),
            "definition_snapshot": {"agent_definition": {
                "system_prompt": "sys", "model_config": {},
            }},
            "input": {"message": "hi"},
        }

    @patch("apps.agents.execution.build_agent_engine")
    def test_success_returns_normalized_output(self, mock_factory):
        engine = MagicMock()
        engine.complete.return_value = LLMResponse(
            content="hello", usage=TokenUsage(), model="deepseek-chat"
        )
        mock_factory.return_value = engine
        sink = MagicMock(cancelled=False)
        output = execute_agent_completion(self._payload(self.organization.id), sink)
        self.assertEqual(output["result"], "hello")
        self.assertEqual(output["model"], "deepseek-chat")
        sink.emit.assert_any_call("output.delta", {"text": "hello"})

    @patch("apps.agents.execution.build_agent_engine")
    def test_failure_raises_for_coordinator(self, mock_factory):
        mock_factory.return_value.complete.return_value = LLMResponse(
            content="", usage=TokenUsage(), model="deepseek-chat",
            success=False, error="boom",
        )
        with self.assertRaisesMessage(RuntimeError, "boom"):
            execute_agent_completion(
                self._payload(self.organization.id), MagicMock(cancelled=False)
            )

    @patch("apps.agents.execution.build_agent_engine")
    def test_success_serializes_usage(self, mock_factory):
        mock_factory.return_value.complete.return_value = LLMResponse(
            content="hello",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            model="deepseek-chat",
        )
        output = execute_agent_completion(
            self._payload(self.organization.id), MagicMock(cancelled=False)
        )
        self.assertEqual(output["usage"]["total_tokens"], 8)

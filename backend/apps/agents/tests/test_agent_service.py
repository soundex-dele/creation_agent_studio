"""Tests for build_agent_engine factory + AgentService.execute."""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.test.utils import override_settings

from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm.factory import build_agent_engine

from apps.agents.models import Agent, AgentCategory
from apps.agents.services.agent_service import AgentService
from apps.users.models import User
from modules.catalog.models import AgentDraft


class BuildAgentEngineTest(TestCase):
    @override_settings(GRAPHFLOW_API_KEY="key-123", GRAPHFLOW_BASE_URL="https://example.com/v1")
    def test_builds_engine_from_settings(self):
        engine = build_agent_engine()
        self.assertIsNotNone(engine)


class AgentServiceExecuteTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.category = AgentCategory.objects.create(name="c", slug="c")
        self.agent = Agent.objects.create(
            category=self.category,
            name="a",
            slug="a",
            description="d",
            created_by=self.user,
            organization=self.user.organization_memberships.get().organization,
        )
        AgentDraft.objects.create(
            organization=self.agent.organization, agent=self.agent,
            updated_by=self.user,
            content={'system_prompt': 'sys', 'model_config': {},
                     'skill_bindings': []})

    def _engine_returning(self, response):
        engine = MagicMock()
        engine.complete.return_value = response
        return engine

    @patch("apps.agents.services.agent_service.build_agent_engine")
    def test_execute_success_marks_completed(self, mock_factory):
        resp = LLMResponse(content="hello", usage=TokenUsage(), model="deepseek-chat")
        mock_factory.return_value = self._engine_returning(resp)

        execution = AgentService.execute(self.agent, self.user, {"q": "hi"})

        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.output_data["result"], "hello")
        self.assertEqual(execution.output_data["model"], "deepseek-chat")

    @patch("apps.agents.services.agent_service.build_agent_engine")
    def test_execute_failure_marks_failed(self, mock_factory):
        resp = LLMResponse(
            content="", usage=TokenUsage(), model="deepseek-chat",
            success=False, error="boom",
        )
        mock_factory.return_value = self._engine_returning(resp)

        execution = AgentService.execute(self.agent, self.user, {"q": "hi"})

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.error_message, "boom")

    @patch("apps.agents.services.agent_service.build_agent_engine")
    def test_execute_unexpected_exception_marks_failed(self, mock_factory):
        mock_factory.return_value.complete.side_effect = RuntimeError("kaboom")

        execution = AgentService.execute(self.agent, self.user, {"q": "hi"})

        self.assertEqual(execution.status, "failed")
        self.assertIn("kaboom", execution.error_message)

    @patch("apps.agents.services.agent_service.build_agent_engine")
    def test_execute_success_serializes_usage(self, mock_factory):
        resp = LLMResponse(
            content="hello",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            model="deepseek-chat",
        )
        mock_factory.return_value = self._engine_returning(resp)

        execution = AgentService.execute(self.agent, self.user, {"q": "hi"})

        self.assertEqual(execution.output_data["usage"]["total_tokens"], 8)

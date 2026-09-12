"""Tests for the non-streaming send_message endpoint."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from modules.catalog.models import AgentDraft
from apps.conversations.models import Conversation, Message
from core.agent_engine.models import LLMResponse, TokenUsage

User = get_user_model()


class SendMessageTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='u2', password='p')
        self.client.force_authenticate(user=self.user)
        self.conversation = Conversation.objects.create(user=self.user, title='T')

    @patch('apps.conversations.views.build_agent_engine')
    def test_send_message_returns_assistant_content(self, mock_factory):
        engine = MagicMock()
        engine.complete.return_value = LLMResponse(
            content='reply', usage=TokenUsage(), model='deepseek-chat')
        mock_factory.return_value = engine

        url = f'/api/conversations/{self.conversation.id}/send_message/'
        response = self.client.post(url, {'content': 'hello'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['assistant_message']['content'], 'reply')

        assistant_msgs = Message.objects.filter(
            conversation=self.conversation, role='assistant')
        self.assertEqual(assistant_msgs.count(), 1)
        self.assertEqual(assistant_msgs.first().content, 'reply')

    @patch('apps.conversations.views.build_agent_engine')
    def test_send_message_llm_failure_returns_500(self, mock_factory):
        engine = MagicMock()
        engine.complete.return_value = LLMResponse(
            content='', usage=TokenUsage(), model='deepseek-chat',
            success=False, error='nope')
        mock_factory.return_value = engine

        url = f'/api/conversations/{self.conversation.id}/send_message/'
        response = self.client.post(url, {'content': 'hello'})

        self.assertEqual(response.status_code, 500)

    @patch('apps.conversations.views.build_agent_engine')
    def test_send_message_uses_bound_agent_system_prompt(self, mock_factory):
        """send_message 使用对话所绑定 agent 的 system_prompt（而非全局默认）。"""
        engine = MagicMock()
        engine.complete.return_value = LLMResponse(
            content='reply', usage=TokenUsage(), model='deepseek-chat')
        mock_factory.return_value = engine

        category = AgentCategory.objects.create(name='C', slug='cat-c')
        agent = Agent.objects.create(
            name='A', slug='agent-a', description='d',
            category=category, created_by=self.user,
            organization=self.user.organization_memberships.get().organization)
        AgentDraft.objects.create(
            organization=agent.organization, agent=agent, updated_by=self.user,
            content={'system_prompt': '你是专属助手', 'model_config': {}})
        conv = Conversation.objects.create(user=self.user, title='T', agent=agent)

        url = f'/api/conversations/{conv.id}/send_message/'
        self.client.post(url, {'content': 'hi'})

        sent_messages = engine.complete.call_args[0][0]
        self.assertEqual(sent_messages[0],
                         {'role': 'system', 'content': '你是专属助手'})

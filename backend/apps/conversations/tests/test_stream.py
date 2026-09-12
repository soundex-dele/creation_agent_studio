"""Tests for the GraphFlow event-stream conversation endpoints."""
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from modules.catalog.models import AgentDraft
from apps.conversations.models import (
    AgentItem,
    AgentServerRequest,
    AgentThread,
    AgentTurn,
    Conversation,
    Message,
)
from core.agent_engine.sdk_loader import load_sdk

User = get_user_model()


class StreamEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.client.force_authenticate(user=self.user)
        self.conversation = Conversation.objects.create(user=self.user, title='Test')
        self.sdk = load_sdk()

    def fake_session(self, events):
        session = MagicMock()
        session.agent_id = 'agent-test'
        session.stream_lock = threading.Lock()
        session.wait_for_event.side_effect = list(events)
        return session

    def completed_events(self, content='你好世界'):
        return [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                content='你好',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.COMPLETED.value,
                content=content,
                usage=self.sdk.EventUsage(total_tokens=8),
            ),
        ]

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_returns_graphflow_and_done_events(self, get_or_create):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            get_or_create.return_value = self.fake_session(self.completed_events())
            response = self.client.post(
                f'/api/conversations/{self.conversation.id}/stream/',
                {'message': 'Hello'},
            )
            content = b''.join(response.streaming_content).decode('utf-8')

            expected = (
                Path(directory) / 'users' / str(self.user.id) / 'system'
            ).resolve()
            self.assertEqual(
                Path(get_or_create.call_args.kwargs['working_directory']), expected)
            self.conversation.refresh_from_db()
            self.assertEqual(
                Path(self.conversation.working_directory), expected)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        self.assertEqual(response['Cache-Control'], 'no-cache')
        self.assertIn('event: engine', content)
        self.assertIn('"type": "progress"', content)
        self.assertIn('"type": "completed"', content)
        self.assertIn('event: done', content)

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_protocol_v2_emits_codex_events_and_persists_items(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='Hello',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.COMPLETED.value,
                content='Hello',
                usage=self.sdk.EventUsage(total_tokens=2),
            ),
        ]
        get_or_create.return_value = self.fake_session(events)

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Say hello', 'protocol_version': 2},
            format='json',
        )
        content = b''.join(response.streaming_content).decode('utf-8')

        self.assertIn('event: turn/started', content)
        self.assertIn('event: item/started', content)
        self.assertIn('event: item/agentMessage/delta', content)
        self.assertIn('event: item/completed', content)
        self.assertIn('event: turn/completed', content)
        thread = AgentThread.objects.get(conversation=self.conversation)
        turn = AgentTurn.objects.get(thread=thread)
        item = AgentItem.objects.get(turn=turn, item_type='agentMessage')
        self.assertEqual(turn.status, AgentTurn.Status.COMPLETED)
        self.assertEqual(turn.usage['total_tokens'], 2)
        self.assertEqual(item.content, 'Hello')

    def test_stream_requires_authentication(self):
        client = APIClient()
        response = client.post(
            f'/api/conversations/{self.conversation.id}/stream/', {'message': 'Hello'}
        )
        self.assertIn(response.status_code, [401, 403])

    def test_stream_requires_message_field(self):
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/', {}
        )
        self.assertEqual(response.status_code, 400)

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_applies_composer_context(self, get_or_create):
        self.user.role = 'admin'
        self.user.save(update_fields=['role'])
        session = self.fake_session(self.completed_events())
        get_or_create.return_value = session
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {
                'message': 'Create it',
                'permission_mode': 'allow_all',
                'skills': ['storytelling'],
            },
            format='json',
        )
        b''.join(response.streaming_content)

        self.assertFalse(get_or_create.call_args.kwargs['enable_permissions'])
        submitted = session.submit.call_args.args[0]
        self.assertEqual(submitted, 'Create it')
        self.assertEqual(
            session.submit.call_args.kwargs['preload_skills'], ['storytelling']
        )
        user_message = Message.objects.get(
            conversation=self.conversation, role='user'
        )
        self.assertEqual(
            user_message.metadata['composer']['skills'], ['storytelling']
        )

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_surfaces_loaded_skills(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.SKILL.value,
                content=(
                    '{"event":"skills_loaded","skills":["storytelling"],'
                    '"missing":[]}'
                ),
            ),
            *self.completed_events(),
        ]
        get_or_create.return_value = self.fake_session(events)
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Create it', 'skills': ['storytelling']},
            format='json',
        )
        content = b''.join(response.streaming_content).decode('utf-8')

        self.assertIn('"loaded_skills": ["storytelling"]', content)
        assistant = Message.objects.get(
            conversation=self.conversation, role='assistant'
        )
        self.assertEqual(
            assistant.metadata['graphflow']['loaded_skills'], ['storytelling']
        )

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_switches_agent_system_prompt(self, get_or_create):
        category = AgentCategory.objects.create(name='Writing', slug='writing')
        agent = Agent.objects.create(
            category=category,
            name='Writer',
            slug='writer',
            description='Writes',
            created_by=self.user,
            organization=self.user.organization_memberships.get().organization,
        )
        AgentDraft.objects.create(
            organization=agent.organization, agent=agent, updated_by=self.user,
            content={'system_prompt': 'You are the writer agent.', 'model_config': {}})
        get_or_create.return_value = self.fake_session(self.completed_events())

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Write', 'agent_id': agent.id},
            format='json',
        )
        b''.join(response.streaming_content)

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.agent_id, agent.id)
        self.assertEqual(
            get_or_create.call_args.kwargs['system_prompt'],
            'You are the writer agent.',
        )
        self.assertEqual(
            get_or_create.return_value.submit.call_args.kwargs['system_prompt'],
            'You are the writer agent.',
        )

    def test_composer_options_lists_configured_skills(self):
        with TemporaryDirectory() as directory:
            skill_dir = Path(directory) / 'storytelling'
            skill_dir.mkdir()
            (skill_dir / 'SKILL.md').write_text(
                '---\nname: storytelling\ndescription: Build a narrative\n---\n',
                encoding='utf-8',
            )
            with override_settings(GRAPHFLOW_SKILLS_DIRECTORY=directory):
                response = self.client.get('/api/conversations/composer-options/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['skills'], [{
            'name': 'storytelling',
            'description': 'Build a narrative',
        }])

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_saves_messages_and_title(self, get_or_create):
        conversation = Conversation.objects.create(user=self.user, title='')
        get_or_create.return_value = self.fake_session(self.completed_events())
        response = self.client.post(
            f'/api/conversations/{conversation.id}/stream/',
            {'message': '测试消息'},
        )
        b''.join(response.streaming_content)

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, '测试消息')
        self.assertEqual(
            Message.objects.get(conversation=conversation, role='user').content,
            '测试消息',
        )
        assistant = Message.objects.get(conversation=conversation, role='assistant')
        self.assertEqual(assistant.content, '你好世界')
        self.assertEqual(assistant.metadata['graphflow']['usage']['total_tokens'], 8)

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_persists_tool_calls_in_assistant_metadata(self, get_or_create):
        tool_start = self.sdk.EventToolCall(
            id='tool-1', name='Read', input='{"path":"demo.txt"}'
        )
        tool_end = self.sdk.EventToolCall(
            id='tool-1', name='Read', input='{"path":"demo.txt"}',
            result='{"content":"hello"}', status='succeeded',
        )
        events = [
            self.sdk.Event(
                agent_id='agent-test', type=self.sdk.EventType.TOOL_START.value,
                tool_call=tool_start,
            ),
            self.sdk.Event(
                agent_id='agent-test', type=self.sdk.EventType.TOOL_END.value,
                tool_call=tool_end,
            ),
            *self.completed_events('完成'),
        ]
        get_or_create.return_value = self.fake_session(events)

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/', {'message': '读取文件'}
        )
        b''.join(response.streaming_content)

        assistants = Message.objects.filter(
            conversation=self.conversation, role='assistant'
        ).order_by('created_at', 'id')
        self.assertEqual(assistants.count(), 2)
        tool_message = assistants.get(metadata__graphflow__message_kind='tool')
        content_message = assistants.get(metadata__graphflow__message_kind='content')
        self.assertEqual(tool_message.content, '')
        self.assertEqual(content_message.content, '完成')
        tool_calls = tool_message.metadata['graphflow']['tool_calls']
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]['name'], 'Read')
        self.assertEqual(tool_calls[0]['status'], 'succeeded')
        self.assertEqual(tool_calls[0]['result'], '{"content":"hello"}')

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_preserves_content_emitted_with_tool_calls(self, get_or_create):
        tool = self.sdk.EventToolCall(
            id='tool-mixed', name='Read', input='{"path":"demo.txt"}'
        )
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.THINKING.value,
                content='internal reasoning',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='I will inspect ',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='the file first.',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.TOOL_START.value,
                tool_call=tool,
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.COMPLETED.value,
                content='',
                usage=self.sdk.EventUsage(total_tokens=5),
            ),
        ]
        get_or_create.return_value = self.fake_session(events)

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Read the file'},
        )
        body = b''.join(response.streaming_content).decode('utf-8')

        self.assertIn('"is_assistant_content": true', body)
        assistants = list(Message.objects.filter(
            conversation=self.conversation, role='assistant'
        ).order_by('created_at', 'id'))
        self.assertEqual(len(assistants), 2)
        self.assertEqual(assistants[0].content, 'I will inspect the file first.')
        self.assertEqual(
            assistants[0].metadata['graphflow']['message_kind'], 'content'
        )
        self.assertEqual(assistants[1].content, '')
        self.assertEqual(
            assistants[1].metadata['graphflow']['message_kind'], 'tool'
        )

    @override_settings(GRAPHFLOW_PROVIDER='anthropic')
    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_accepts_anthropic_content_snapshots(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='Hello',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='Hello, world',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.COMPLETED.value,
                content='Hello, world',
            ),
        ]
        get_or_create.return_value = self.fake_session(events)

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Say hello'},
        )
        body = b''.join(response.streaming_content).decode('utf-8')

        self.assertIn('"content_mode": "snapshot"', body)
        assistant = Message.objects.get(
            conversation=self.conversation, role='assistant')
        self.assertEqual(assistant.content, 'Hello, world')

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_completed_content_is_reemitted_as_progress(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.COMPLETED.value,
                content='Final answer',
                usage=self.sdk.EventUsage(total_tokens=3),
            ),
        ]
        get_or_create.return_value = self.fake_session(events)

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Answer'},
        )
        body = b''.join(response.streaming_content).decode('utf-8')

        progress_position = body.index(
            '"type": "progress", "agent_id": "agent-test", '
            '"content": "Final answer"'
        )
        completed_position = body.index('"type": "completed"')
        self.assertLess(progress_position, completed_position)
        assistant = Message.objects.get(
            conversation=self.conversation, role='assistant'
        )
        self.assertEqual(assistant.content, 'Final answer')

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_surfaces_engine_failure(self, get_or_create):
        session = self.fake_session([])
        session.submit.side_effect = RuntimeError('API Error')
        get_or_create.return_value = session
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Hello'},
        )
        content = b''.join(response.streaming_content).decode('utf-8')
        self.assertIn('event: engine', content)
        self.assertIn('"type": "failed"', content)
        self.assertIn('API Error', content)

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_protocol_v2_surfaces_failure_as_turn_completion(self, get_or_create):
        session = self.fake_session([])
        session.submit.side_effect = RuntimeError('API Error')
        get_or_create.return_value = session

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': 'Hello', 'protocol_version': 2},
            format='json',
        )
        content = b''.join(response.streaming_content).decode('utf-8')

        self.assertIn('event: turn/started', content)
        self.assertIn('event: turn/completed', content)
        self.assertIn('"status": "failed"', content)
        self.assertNotIn('event: engine', content)
        turn = AgentTurn.objects.get(thread__conversation=self.conversation)
        self.assertEqual(turn.status, AgentTurn.Status.FAILED)
        self.assertEqual(turn.error['message'], 'API Error')

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_persists_visible_content_before_completion(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='尚未完成但已经显示的内容',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.FAILED.value,
                content='执行中断',
            ),
        ]
        get_or_create.return_value = self.fake_session(events)

        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': '生成文章'},
        )
        b''.join(response.streaming_content)

        assistant = Message.objects.get(
            conversation=self.conversation, role='assistant')
        self.assertEqual(assistant.content, '尚未完成但已经显示的内容')
        self.assertEqual(
            assistant.metadata['graphflow']['lifecycle'], 'streaming')

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_defers_content_persistence_until_stream_ends(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='第一段',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='第二段',
            ),
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.COMPLETED.value,
                content='第一段第二段',
            ),
        ]
        get_or_create.return_value = self.fake_session(events)
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': '生成内容'},
        )
        stream = iter(response.streaming_content)

        first_frame = next(stream).decode('utf-8')
        self.assertIn('第一段', first_frame)
        self.assertFalse(Message.objects.filter(
            conversation=self.conversation, role='assistant').exists())

        b''.join(stream)
        assistant = Message.objects.get(
            conversation=self.conversation, role='assistant')
        self.assertEqual(assistant.content, '第一段第二段')

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_flushes_cached_content_when_client_disconnects(self, get_or_create):
        events = [
            self.sdk.Event(
                agent_id='agent-test',
                type=self.sdk.EventType.PROGRESS.value,
                progress_category=self.sdk.ProgressCategory.CONTENT.value,
                content='断开前已显示',
            ),
        ]
        session = self.fake_session(events)
        get_or_create.return_value = session
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/stream/',
            {'message': '生成内容'},
        )
        stream = iter(response.streaming_content)

        next(stream)
        self.assertFalse(Message.objects.filter(
            conversation=self.conversation, role='assistant').exists())
        response.close()

        assistant = Message.objects.get(
            conversation=self.conversation, role='assistant')
        self.assertEqual(assistant.content, '断开前已显示')
        session.cancel.assert_called_once()

    @patch('apps.conversations.views.session_registry.get_or_create')
    def test_stream_uses_bound_agent_system_prompt(self, get_or_create):
        category = AgentCategory.objects.create(name='C', slug='cat-stream')
        agent = Agent.objects.create(
            name='A', slug='agent-stream', description='d',
            category=category, created_by=self.user,
            organization=self.user.organization_memberships.get().organization,
        )
        AgentDraft.objects.create(
            organization=agent.organization, agent=agent, updated_by=self.user,
            content={'system_prompt': '你是专属直播助手', 'model_config': {}})
        conversation = Conversation.objects.create(user=self.user, title='T', agent=agent)
        get_or_create.return_value = self.fake_session(self.completed_events('回复'))
        response = self.client.post(
            f'/api/conversations/{conversation.id}/stream/', {'message': 'hi'}
        )
        b''.join(response.streaming_content)

        self.assertEqual(
            get_or_create.call_args.kwargs['system_prompt'], '你是专属直播助手'
        )

    @patch('apps.conversations.views.session_registry.get')
    def test_resume_passes_answer_to_active_session(self, get_session):
        session = MagicMock()
        session.resume.return_value = self.sdk.ResumeStatus.ACCEPTED
        get_session.return_value = session
        thread = AgentThread.objects.create(conversation=self.conversation)
        turn = AgentTurn.objects.create(
            thread=thread, status=AgentTurn.Status.IN_PROGRESS)
        server_request = AgentServerRequest.objects.create(
            thread=thread,
            turn=turn,
            remote_id='request-1',
            method='tool/requestUserInput',
        )
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/resume/',
            {'text': '', 'selections': ['allow']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        session.resume.assert_called_once_with(text='', selections=['allow'])
        server_request.refresh_from_db()
        self.assertEqual(
            server_request.status, AgentServerRequest.Status.RESOLVED)

    @patch('apps.conversations.views.session_registry.get')
    def test_cancel_passes_to_active_session(self, get_session):
        session = MagicMock()
        session.cancel.return_value = self.sdk.CancelStatus.ACCEPTED
        get_session.return_value = session
        response = self.client.post(
            f'/api/conversations/{self.conversation.id}/cancel-turn/', {}
        )
        self.assertEqual(response.status_code, 200)
        session.cancel.assert_called_once_with()

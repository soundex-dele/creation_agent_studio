"""Tests for conversation creation and agent binding.

每个对话必然绑定一个 agent：未指定 agent_id 时回退到通用 agent (slug=general)。
"""
from django.contrib.auth import get_user_model
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.conversations.models import Message

User = get_user_model()


class CreateConversationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='creator', password='p')
        self.client.force_authenticate(user=self.user)

        self.category = AgentCategory.objects.create(name='写作', slug='writing')
        self.agent = Agent.objects.create(
            name='脚本助手',
            slug='script-writer',
            description='写脚本',
            category=self.category,
            created_by=self.user,
        )

    def test_create_without_agent_id_binds_general(self):
        """未指定 agent_id 时自动绑定通用 agent。"""
        general = Agent.objects.get(slug='general')

        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            response = self.client.post('/api/v1/conversations/', {})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['agent']['id'], general.id)
        conversation = self.user.conversations.get(id=response.data['id'])
        expected = (
            Path(directory) / 'organizations' / str(conversation.organization_id)
            / 'conversations' / str(conversation.id)
        ).resolve()
        self.assertEqual(Path(response.data['working_directory']), expected)

    def test_system_conversations_have_isolated_working_directories(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            first = self.client.post('/api/v1/conversations/', {}, format='json')
            second = self.client.post('/api/v1/conversations/', {}, format='json')
            first_workspace = Path(first.data['working_directory'])
            second_workspace = Path(second.data['working_directory'])
            (first_workspace / 'first-only.txt').write_text(
                'first conversation', encoding='utf-8')

            listing = self.client.get(
                f"/api/v1/conversations/{second.data['id']}/workspace-files/")

        self.assertNotEqual(first_workspace, second_workspace)
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data['file_count'], 0)

    def test_legacy_shared_system_directory_is_replaced_without_copying_files(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            created = self.client.post('/api/v1/conversations/', {}, format='json')
            conversation = self.user.conversations.get(id=created.data['id'])
            legacy = (
                Path(directory) / 'organizations' / str(conversation.organization_id)
                / 'system'
            ).resolve()
            legacy.mkdir(parents=True)
            (legacy / 'unowned.txt').write_text('legacy', encoding='utf-8')
            conversation.working_directory = str(legacy)
            conversation.save(update_fields=['working_directory'])

            listing = self.client.get(
                f"/api/v1/conversations/{conversation.id}/workspace-files/")
            conversation.refresh_from_db()

        expected = (
            Path(directory) / 'organizations' / str(conversation.organization_id)
            / 'conversations' / str(conversation.id)
        ).resolve()
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(Path(conversation.working_directory), expected)
        self.assertEqual(listing.data['file_count'], 0)

    def test_create_with_agent_id_binds_specified(self):
        """指定 agent_id 时绑定到该 agent。"""
        response = self.client.post('/api/v1/conversations/', {'agent_id': self.agent.id})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['agent']['id'], self.agent.id)
        self.assertEqual(response.data['agent']['name'], '脚本助手')

    def test_retrieve_created_conversation_resolves_organization(self):
        created = self.client.post(
            '/api/v1/conversations/', {'agent_id': self.agent.id})
        conversation = self.user.conversations.get(id=created.data['id'])
        Message.objects.create(
            conversation=conversation, role='user', content='保留的历史消息')

        response = self.client.get(f'/api/v1/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['messages'][0]['content'], '保留的历史消息')

    def test_create_with_invalid_agent_id_falls_back_to_general(self):
        """无效 agent_id 回退到通用 agent，而不是报错。"""
        general = Agent.objects.get(slug='general')

        response = self.client.post('/api/v1/conversations/', {'agent_id': 999999})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['agent']['id'], general.id)

    def test_create_can_use_an_allowed_system_directory(self):
        with TemporaryDirectory() as directory:
            selected = Path(directory) / 'selected'
            selected.mkdir()
            with override_settings(APPLICATION_RUNTIME_ALLOWED_ROOTS=[directory]):
                response = self.client.post(
                    '/api/v1/conversations/',
                    {'working_directory': str(selected)},
                    format='json',
                )

            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(
                Path(response.data['working_directory']), selected.resolve())

    def test_create_rejects_a_system_directory_outside_allowed_roots(self):
        with TemporaryDirectory() as allowed, TemporaryDirectory() as outside:
            with override_settings(APPLICATION_RUNTIME_ALLOWED_ROOTS=[allowed]):
                response = self.client.post(
                    '/api/v1/conversations/',
                    {'working_directory': outside},
                    format='json',
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn('working_directory', response.data)

    def test_workspace_files_lists_and_previews_system_conversation_files(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            created = self.client.post('/api/v1/conversations/', {}, format='json')
            workspace = Path(created.data['working_directory'])
            (workspace / 'test.txt').write_text(
                'created by agent', encoding='utf-8')

            listing = self.client.get(
                f"/api/v1/conversations/{created.data['id']}/workspace-files/")
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual(listing.data['working_directory'], str(workspace))
            self.assertEqual(listing.data['file_count'], 1)
            self.assertEqual(listing.data['entries'][0]['path'], 'test.txt')

            preview = self.client.get(
                f"/api/v1/conversations/{created.data['id']}/workspace-files/",
                {'path': 'test.txt'},
            )
            self.assertEqual(preview.status_code, 200, preview.data)
            self.assertEqual(preview.data['preview_kind'], 'text')
            self.assertEqual(preview.data['content'], 'created by agent')

    def test_workspace_file_preview_rejects_path_traversal(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            created = self.client.post('/api/v1/conversations/', {}, format='json')
            response = self.client.get(
                f"/api/v1/conversations/{created.data['id']}/workspace-files/",
                {'path': '../outside.txt'},
            )

        self.assertEqual(response.status_code, 400)

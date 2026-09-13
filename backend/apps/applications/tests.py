from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.enterprise.models import Membership, Organization
from apps.users.models import User
from modules.catalog.models import (
    AgentDraft, ApplicationDraft, ChatApplicationRevision,
)
from modules.catalog.services import publish_application

from .models import Application, ApplicationCategory, ChatApplication, Skill


class LegacyDefinitionMigrationTest(TestCase):
    def test_seeded_chat_and_agent_definitions_survive_schema_migration(self):
        application = Application.objects.get(slug='creative-chat')
        definition = application.draft.content
        self.assertIsNotNone(application.organization_id)
        self.assertEqual(definition['kind'], 'chat')
        self.assertEqual(definition['renderer_key'], 'chat')
        self.assertEqual(len(definition['agent_bindings']), 1)
        self.assertTrue(definition['agent_bindings'][0]['is_default'])
        self.assertTrue(definition['guided_prompts'])

        agent = Agent.objects.get(slug='general')
        self.assertIsNotNone(agent.organization_id)
        self.assertIn('视频创作助手', agent.draft.content['system_prompt'])


class ChatApplicationBoundaryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('app-owner', password='secret')
        self.organization = Organization.objects.create(
            name='Studio', slug='studio-test', owner=self.user)
        Membership.objects.create(
            organization=self.organization, user=self.user,
            role=Membership.Role.OWNER)
        self.app_category = ApplicationCategory.objects.create(
            name='Test apps', slug='test-apps')
        agent_category = AgentCategory.objects.create(
            name='Test agents', slug='test-agents')
        self.agent = Agent.objects.create(
            category=agent_category, name='Writer', slug='writer-test',
            description='Writes', created_by=self.user,
            organization=self.organization)
        AgentDraft.objects.create(
            organization=self.organization, agent=self.agent,
            updated_by=self.user, content={
                'system_prompt': 'Write', 'model_config': {},
                'skill_bindings': [],
            })
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {'HTTP_X_ORGANIZATION_ID': str(self.organization.id)}

    def _create_chat(self, *, slug='chat-test'):
        response = self.client.post(
            f'/api/v1/organizations/{self.organization.id}/applications', {
            'category_id': self.app_category.id,
            'name': 'Chat',
            'slug': slug,
            'description': 'Chat app',
            'content': {
                'kind': 'chat',
                'executor_kind': 'agent',
                'renderer_key': 'chat',
                'executor_key': 'agent-chat',
                'default_config': {'guided_entry_prompt_key': 'copy'},
                'chat_profile': {
                    'welcome_message': 'Welcome',
                    'allow_agent_selection': False,
                    'allow_skill_selection': True,
                    'allow_extra_skills': False,
                    'starter_layout': 'cards',
                },
                'agent_bindings': [{
                    'agent_id': self.agent.id, 'is_default': True, 'order': 0,
                }],
                'guided_prompts': [{
                    'id': 'copy', 'key': 'copy', 'title': 'Copy',
                    'prompt_template': '主题：{topic}\n语气：{tone}',
                    'action': 'preview', 'is_featured': True, 'order': 0,
                    'questions': [
                        {'id': 'topic', 'key': 'topic', 'label': '主题',
                         'type': 'text', 'required': True, 'options': []},
                        {'id': 'tone', 'key': 'tone', 'label': '语气',
                         'type': 'single_choice', 'required': False,
                         'options': [{'value': 'friendly', 'label': '亲切'}]},
                    ],
                }],
            },
        }, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        application = Application.objects.get(slug=slug)
        runtime = self.client.get(f'/api/v1/apps/{slug}/', **self.headers)
        self.assertEqual(runtime.status_code, 200, runtime.data)
        return runtime, application

    def test_chat_fields_live_only_in_the_typed_draft(self):
        response, application = self._create_chat()
        self.assertTrue(ChatApplication.objects.filter(application=application).exists())
        for field in ('renderer_key', 'executor_key', 'default_config'):
            with self.assertRaises(FieldDoesNotExist):
                Application._meta.get_field(field)
        self.assertEqual(application.draft.content['kind'], 'chat')
        self.assertEqual(response.data['agent_bindings'][0]['agent_name'], 'Writer')
        self.assertEqual(response.data['chat_profile']['welcome_message'], 'Welcome')

    def test_non_chat_runtime_has_no_chat_members(self):
        response = self.client.post(
            f'/api/v1/organizations/{self.organization.id}/applications', {
            'category_id': self.app_category.id,
            'name': 'Task', 'slug': 'task-test', 'description': 'Task app',
            'content': {
                'kind': 'task', 'executor_kind': 'media',
                'renderer_key': 'generic-task', 'executor_key': 'task-executor',
            },
        }, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        runtime = self.client.get('/api/v1/apps/task-test/', **self.headers)
        self.assertNotIn('agent_bindings', runtime.data)
        self.assertNotIn('skill_bindings', runtime.data)
        self.assertNotIn('guided_prompts', runtime.data)
        self.assertNotIn('chat_profile', runtime.data)

    def test_publish_creates_chat_revision_subtype(self):
        _response, application = self._create_chat()
        revision = publish_application(
            application=application, actor=self.user,
            expected_draft_version=application.draft.version)
        self.assertTrue(
            ChatApplicationRevision.objects.filter(revision=revision).exists())

    def test_compose_and_conversation_use_chat_definition(self):
        _response, application = self._create_chat()
        composed = self.client.post(
            f'/api/v1/apps/{application.slug}/compose-prompt/',
            {'prompt_id': 'copy', 'answers': {
                'topic': '咖啡', 'tone': 'friendly'}},
            format='json', **self.headers)
        self.assertEqual(composed.status_code, 200, composed.data)
        self.assertEqual(composed.data['prompt'], '主题：咖啡\n语气：亲切')

        created = self.client.post('/api/v1/conversations/', {
            'application_id': application.id,
        }, format='json', **self.headers)
        self.assertEqual(created.status_code, 201, created.data)
        conversation = self.user.conversations.get(id=created.data['id'])
        self.assertEqual(conversation.chat_application_id, application.id)

    def test_user_selected_application_skill_is_bound_only_once(self):
        skill = Skill.objects.create(
            organization=self.organization,
            owner=self.user,
            slug='shared-skill',
            name='Shared Skill',
            visibility=Skill.Visibility.ORGANIZATION,
        )
        _response, application = self._create_chat()
        application.draft.content['skill_bindings'] = [{
            'skill_id': str(skill.id),
            'mode': 'default',
            'config': {},
            'order': 0,
        }]
        application.draft.save(update_fields=['content'])

        created = self.client.post('/api/v1/conversations/', {
            'application_id': application.id,
            'skill_ids': [str(skill.id)],
        }, format='json', **self.headers)

        self.assertEqual(created.status_code, 201, created.data)
        conversation = self.user.conversations.get(id=created.data['id'])
        self.assertEqual(conversation.skill_bindings.count(), 1)

    def test_chat_update_replaces_the_single_draft_source(self):
        _response, application = self._create_chat()
        version = application.draft.version
        content = application.draft.content
        content['chat_profile'] = {
            **content['chat_profile'], 'welcome_message': 'Updated'}
        response = self.client.put(
            f'/api/v1/organizations/{self.organization.id}/applications/'
            f'{application.id}/draft',
            {'expected_version': version, 'content': content},
            format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        application.draft.refresh_from_db()
        self.assertEqual(application.draft.version, version + 1)
        self.assertEqual(
            application.draft.content['chat_profile']['welcome_message'],
            'Updated')

    def test_rejects_private_agent_from_another_tenant(self):
        outsider = User.objects.create_user('outsider', password='secret')
        other_org = outsider.organization_memberships.get().organization
        other_category = AgentCategory.objects.create(
            name='Other agents', slug='other-agents')
        private_agent = Agent.objects.create(
            category=other_category, name='Private', slug='private-agent',
            description='Private', is_public=False, created_by=outsider,
            organization=other_org)
        _response, application = self._create_chat(slug='rejected')
        application.draft.content['agent_bindings'] = [{
            'agent_id': private_agent.id, 'is_default': True,
        }]
        application.draft.save(update_fields=['content'])
        response = self.client.post(
            f'/api/v1/organizations/{self.organization.id}/applications/'
            f'{application.id}/revisions',
            {'expected_draft_version': application.draft.version},
            format='json', **self.headers)
        self.assertEqual(response.status_code, 422, response.data)

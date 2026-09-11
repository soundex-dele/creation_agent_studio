from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.enterprise.models import Membership, Organization
from apps.conversations.models import Conversation
from apps.projects.models import Project
from apps.users.models import User
from .models import (
    Application, ApplicationAgentBinding, ApplicationCategory,
    ApplicationSkillBinding, ChatApplicationProfile, GuidedOption,
    GuidedPrompt, GuidedQuestion, Skill,
)
from .services import compose_guided_prompt


class ChatApplicationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('app-owner', password='secret')
        self.organization = Organization.objects.create(
            name='Studio', slug='studio-test', owner=self.user)
        Membership.objects.create(
            organization=self.organization, user=self.user,
            role=Membership.Role.OWNER)
        app_category = ApplicationCategory.objects.create(
            name='Test chat', slug='test-chat')
        agent_category = AgentCategory.objects.create(
            name='Test agent', slug='test-agent')
        agent = Agent.objects.create(
            category=agent_category, name='Writer', slug='writer-test',
            description='Writes', system_prompt='Write', created_by=self.user,
            organization=self.organization)
        self.agent = agent
        self.application = Application.objects.create(
            category=app_category, name='Chat', slug='chat-test',
            description='Chat app', created_by=self.user,
            organization=self.organization, kind='chat', renderer_key='chat')
        ChatApplicationProfile.objects.create(application=self.application)
        ApplicationAgentBinding.objects.create(
            application=self.application, agent=agent,
            is_default=True)
        self.prompt = GuidedPrompt.objects.create(
            application=self.application, key='copy', title='Copy',
            prompt_template='主题：{topic}\n语气：{tone}')
        GuidedQuestion.objects.create(
            guided_prompt=self.prompt, key='topic', label='主题',
            type='text', required=True, order=0)
        tone = GuidedQuestion.objects.create(
            guided_prompt=self.prompt, key='tone', label='语气',
            type='single_choice', order=1)
        GuidedOption.objects.create(
            question=tone, value='friendly', label='亲切')

    def test_compose_guided_prompt_uses_option_label(self):
        result = compose_guided_prompt(
            self.prompt, {'topic': '咖啡', 'tone': 'friendly'})
        self.assertEqual(result['prompt'], '主题：咖啡\n语气：亲切')

    def test_compose_guided_prompt_requires_question(self):
        with self.assertRaises(ValidationError):
            compose_guided_prompt(self.prompt, {'tone': 'friendly'})

    def test_chat_application_creates_bound_conversation(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post('/api/conversations/', {
            'application_id': self.application.id,
            'agent_id': self.agent.id,
        }, format='json', HTTP_X_ORGANIZATION_ID=str(self.organization.id))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['application_id'], self.application.id)
        self.assertEqual(response.data['agent']['id'], self.agent.id)

    def test_application_project_history_identifies_its_conversation(self):
        project = Project.objects.create(
            user=self.user,
            organization=self.organization,
            application=self.application,
            title='Chat history',
        )
        conversation = Conversation.objects.create(
            user=self.user,
            organization=self.organization,
            application=self.application,
            project=project,
            agent=self.agent,
            title='Distinct conversation',
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            '/api/projects/',
            HTTP_X_ORGANIZATION_ID=str(self.organization.id),
        )

        self.assertEqual(response.status_code, 200, response.data)
        projects = response.data.get('results', response.data)
        item = next(value for value in projects if value['id'] == project.id)
        self.assertEqual(item['application_kind'], 'chat')
        self.assertEqual(item['conversation_id'], conversation.id)

    def test_discovery_endpoint_rejects_application_create(self):
        outsider = User.objects.create_user('outsider', password='secret')
        other_org = Organization.objects.create(
            name='Other Studio', slug='other-studio-test', owner=outsider)
        other_category = AgentCategory.objects.create(
            name='Other agent', slug='other-agent-test')
        private_agent = Agent.objects.create(
            category=other_category, name='Private', slug='private-agent-test',
            description='Private', system_prompt='Private', is_public=False,
            created_by=outsider, organization=other_org)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post('/api/apps/', {
            'category': self.application.category_id,
            'name': 'Rejected app',
            'slug': 'rejected-app',
            'description': 'Should fail',
            'kind': 'chat',
            'renderer_key': 'chat',
            'agent_bindings': [{
                'agent_id': private_agent.id,
                'is_default': True,
            }],
        }, format='json', HTTP_X_ORGANIZATION_ID=str(self.organization.id))

        self.assertEqual(response.status_code, 405, response.data)

    def test_discovery_endpoint_rejects_application_update(self):
        skill = Skill.objects.create(
            slug='copy-skill', name='Copy skill', owner=self.user,
            organization=self.organization, visibility=Skill.Visibility.PUBLIC)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.patch(
            f'/api/apps/{self.application.slug}/',
            {
                'default_config': {'guided_entry_prompt_key': 'brief'},
                'agent_bindings': [{
                    'agent_id': self.agent.id,
                    'label': self.agent.name,
                    'is_default': True,
                    'order': 0,
                }],
                'skill_bindings': [{
                    'skill_id': str(skill.id),
                    'mode': 'default',
                    'order': 0,
                }],
                'guided_prompts': [{
                    'key': 'brief',
                    'title': 'Create brief',
                    'prompt_template': 'Topic: {topic}',
                    'action': 'preview',
                    'is_featured': True,
                    'order': 0,
                    'questions': [{
                        'key': 'topic',
                        'label': 'Topic',
                        'type': 'text',
                        'required': True,
                        'order': 0,
                        'options': [],
                    }],
                }],
            },
            format='json',
            HTTP_X_ORGANIZATION_ID=str(self.organization.id),
        )

        self.assertEqual(response.status_code, 405, response.data)

    def test_application_detail_reports_edit_permission(self):
        owner_client = APIClient()
        owner_client.force_authenticate(self.user)
        owner_response = owner_client.get(
            f'/api/apps/{self.application.slug}/')
        self.assertTrue(owner_response.data['can_edit'])

        outsider = User.objects.create_user('app-viewer', password='secret')
        outsider_client = APIClient()
        outsider_client.force_authenticate(outsider)
        outsider_response = outsider_client.get(
            f'/api/apps/{self.application.slug}/')
        self.assertFalse(outsider_response.data['can_edit'])

    def test_discovery_endpoint_does_not_validate_or_write_legacy_payloads(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.patch(
            f'/api/apps/{self.application.slug}/',
            {'default_config': {'guided_entry_prompt_key': 'missing'}},
            format='json',
            HTTP_X_ORGANIZATION_ID=str(self.organization.id),
        )

        self.assertEqual(response.status_code, 405, response.data)


class SeededWechatArticleApplicationTest(TestCase):
    def test_application_preloads_write_wechat_article_skill(self):
        application = Application.objects.get(slug='wechat-article-writer')

        self.assertEqual(application.kind, Application.Kind.CHAT)
        self.assertEqual(application.renderer_key, 'chat')
        self.assertEqual(
            application.default_config['guided_entry_prompt_key'],
            'article-brief',
        )
        self.assertEqual(
            application.agent_bindings.get(is_default=True).agent.slug,
            'wechat-article-writer',
        )
        binding = application.skill_bindings.select_related('skill').get()
        self.assertEqual(binding.skill.slug, 'write-wechat-article')
        self.assertEqual(binding.mode, ApplicationSkillBinding.Mode.REQUIRED)
        prompt = application.guided_prompts.get(key='article-brief')
        self.assertEqual(prompt.questions.count(), 7)
        self.assertIn('write-wechat-article Skill', prompt.prompt_template)

    def test_new_conversation_inherits_required_skill(self):
        user = User.objects.create_user('wechat-writer-user', password='secret')
        application = Application.objects.get(slug='wechat-article-writer')
        client = APIClient()
        client.force_authenticate(user)

        response = client.post('/api/conversations/', {
            'application_id': application.id,
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['application_id'], application.id)
        conversation = user.conversations.get(id=response.data['id'])
        binding = conversation.skill_bindings.select_related('skill').get()
        self.assertEqual(binding.skill.slug, 'write-wechat-article')
        self.assertEqual(binding.source, 'app_required')

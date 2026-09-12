"""Tests for agent search and filter endpoints."""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.agents.models import AgentCategory, Agent
from apps.applications.models import (
    Application, ApplicationCategory, ChatApplication, Skill,
)
from apps.enterprise.models import Membership
from modules.catalog.models import AgentDraft, ApplicationDraft

User = get_user_model()


class AgentFilterTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)

        self.cat_video = AgentCategory.objects.create(name='视频制作', slug='video', description='视频相关')
        self.cat_write = AgentCategory.objects.create(name='文案写作', slug='writing', description='写作相关')

        Agent.objects.create(
            name='视频脚本生成器',
            slug='video-script-generator',
            description='自动生成短视频脚本',
            category=self.cat_video,
            is_public=True,
            created_by=self.user
        )
        Agent.objects.create(
            name='种草文案助手',
            slug='copywriting-assistant',
            description='生成种草推荐文案',
            category=self.cat_write,
            is_public=True,
            created_by=self.user
        )

    def test_search_by_name(self):
        response = self.client.get('/api/agents/', {'search': '脚本'})
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], '视频脚本生成器')

    def test_search_by_description(self):
        response = self.client.get('/api/agents/', {'search': '种草'})
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)

    def test_filter_by_category_slug(self):
        response = self.client.get('/api/agents/', {'category': 'video'})
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], '视频脚本生成器')

    def test_search_returns_empty_for_no_match(self):
        response = self.client.get('/api/agents/', {'search': '不存在的智能体'})
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 0)

    def test_combined_search_and_filter(self):
        response = self.client.get('/api/agents/', {'search': '视频', 'category': 'video'})
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)

    def test_viewer_cannot_create_agent_in_organization(self):
        owner = User.objects.create_user(username='agent-owner', password='p')
        organization = owner.organization_memberships.get().organization
        Membership.objects.create(organization=organization, user=self.user,
                                  role=Membership.Role.VIEWER)
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.id))
        response = self.client.post('/api/agents/', {
            'category': self.cat_video.id, 'name': 'Blocked', 'slug': 'blocked-agent',
            'description': 'x', 'system_prompt': 'x', 'is_public': False,
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_mine_filter_is_tenant_scoped(self):
        organization = self.user.organization_memberships.get().organization
        mine = Agent.objects.get(slug='video-script-generator')
        mine.organization = organization
        mine.save(update_fields=['organization'])
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.id))
        response = self.client.get('/api/agents/', {'mine': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data['results']], [mine.id])

    def test_owner_can_create_update_and_delete_agent_with_skills(self):
        organization = self.user.organization_memberships.get().organization
        skill = Skill.objects.create(
            organization=organization,
            owner=self.user,
            slug='story-structure',
            name='故事结构',
            visibility=Skill.Visibility.ORGANIZATION,
        )
        response = self.client.post('/api/agents/', {
            'category': self.cat_write.id,
            'name': '故事助手',
            'slug': 'story-helper',
            'description': '帮助设计故事结构',
            'icon': '✍️',
            'system_prompt': '你是一位故事结构顾问。',
            'skill_ids': [str(skill.id)],
            'is_public': False,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        agent = Agent.objects.get(slug='story-helper')
        self.assertEqual(agent.draft.content['system_prompt'], '你是一位故事结构顾问。')
        self.assertEqual(
            agent.draft.content['skill_bindings'][0]['skill_id'],
            str(skill.id),
        )

        detail = self.client.get(f'/api/agents/{agent.id}/')
        self.assertTrue(detail.data['can_edit'])
        self.assertTrue(detail.data['can_delete'])
        self.assertEqual(detail.data['skill_bindings'][0]['name'], '故事结构')

        response = self.client.patch(f'/api/agents/{agent.id}/', {
            'system_prompt': '你是一位资深故事结构顾问。',
            'skill_ids': [],
        }, format='json')
        self.assertEqual(response.status_code, 200)
        agent.refresh_from_db()
        agent.draft.refresh_from_db()
        self.assertEqual(agent.draft.content['system_prompt'], '你是一位资深故事结构顾问。')
        self.assertEqual(agent.draft.content['skill_bindings'], [])

        response = self.client.delete(f'/api/agents/{agent.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Agent.objects.filter(id=agent.id).exists())

    def test_agent_rejects_inaccessible_skill(self):
        other = User.objects.create_user(username='other-skill-owner', password='p')
        skill = Skill.objects.create(
            organization=other.organization_memberships.get().organization,
            owner=other,
            slug='private-skill',
            name='私有技能',
            visibility=Skill.Visibility.PRIVATE,
        )
        response = self.client.post('/api/agents/', {
            'category': self.cat_write.id,
            'name': 'Invalid Skill Agent',
            'slug': 'invalid-skill-agent',
            'description': 'x',
            'system_prompt': 'x',
            'skill_ids': [str(skill.id)],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('skill_ids', response.data)

    def test_agent_in_use_returns_conflict_on_delete(self):
        organization = self.user.organization_memberships.get().organization
        agent = Agent.objects.create(
            name='Bound Agent',
            slug='bound-agent',
            description='x',
            category=self.cat_write,
            created_by=self.user,
            organization=organization,
        )
        app_category = ApplicationCategory.objects.create(
            name='测试应用', slug='test-apps')
        application = Application.objects.create(
            category=app_category,
            name='Bound App',
            slug='bound-app',
            description='x',
            created_by=self.user,
            organization=organization,
            kind=Application.Kind.CHAT,
        )
        ChatApplication.objects.create(application=application)
        ApplicationDraft.objects.create(
            organization=organization, application=application,
            updated_by=self.user, content={
                'kind': 'chat', 'executor_kind': 'agent',
                'executor_key': 'chat', 'renderer_key': 'chat',
                'agent_bindings': [{'agent_id': agent.id, 'is_default': True}],
            })

        response = self.client.delete(f'/api/agents/{agent.id}/')

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Agent.objects.filter(id=agent.id).exists())

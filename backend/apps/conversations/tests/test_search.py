"""Tests for conversation search endpoint."""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.conversations.models import Conversation

User = get_user_model()


class ConversationSearchTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        organization = self.user.organization_memberships.get().organization

        Conversation.objects.create(
            user=self.user, organization=organization, title='咖啡制作技巧')
        Conversation.objects.create(
            user=self.user, organization=organization, title='视频脚本生成')
        Conversation.objects.create(
            user=self.user, organization=organization, title='旅行 Vlog 策划')

    def test_search_by_title(self):
        response = self.client.get('/api/conversations/', {'search': '咖啡'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], '咖啡制作技巧')

    def test_search_no_match(self):
        response = self.client.get('/api/conversations/', {'search': '不存在的对话'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_list_without_search(self):
        response = self.client.get('/api/conversations/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)

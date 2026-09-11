from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.conversations.models import Conversation


class RemovedConversationStreamTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="stream-user")
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.conversation = Conversation.objects.create(
            user=self.user, organization=self.organization
        )

    def test_conversation_does_not_expose_a_second_stream_implementation(self):
        response = self.client.post(
            f"/api/conversations/{self.conversation.id}/stream/",
            {"message": "hello"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.id),
        )
        self.assertEqual(response.status_code, 404)

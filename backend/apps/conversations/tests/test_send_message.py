from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.conversations.models import Conversation, Message
from modules.execution.models import Run


class DurableConversationRunTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="chat-user")
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        self.conversation = Conversation.objects.create(
            user=self.user,
            organization=self.organization,
            title="Chat",
        )

    def test_send_message_creates_run_instead_of_synchronous_execution(self):
        response = self.client.post(
            f"/api/conversations/{self.conversation.id}/send_message/",
            {"content": "hello"},
            format="json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 202, response.data)
        run = Run.objects.get(pk=response.data["id"])
        self.assertEqual(run.source_type, "conversation")
        self.assertEqual(run.source_id, str(self.conversation.id))
        self.assertEqual(run.executor_kind, Run.ExecutorKind.AGENT)
        self.assertTrue(Message.objects.filter(
            conversation=self.conversation, role="user", content="hello"
        ).exists())

from django.test import TestCase
from rest_framework.test import APIClient


class RemovedParallelAgentApiTest(TestCase):
    def test_parallel_agent_protocol_api_is_removed(self):
        response = APIClient().get("/api/agent/v2/threads/")
        self.assertEqual(response.status_code, 404)

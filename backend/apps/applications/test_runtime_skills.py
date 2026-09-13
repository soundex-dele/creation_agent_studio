from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.applications.models import Skill


class CanonicalSkillApiTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="skill-owner")
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}

    def test_skill_crud_uses_database_catalog(self):
        created = self.client.post(
            "/api/v1/apps/skills/",
            {
                "slug": "storyboard",
                "name": "Storyboard",
                "description": "Build a storyboard",
                "visibility": "organization",
                "source_type": "git",
                "source_uri": "https://example.invalid/storyboard.git",
                "manifest": {"entrypoint": "SKILL.md"},
            },
            format="json",
            **self.headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        skill = Skill.objects.get(pk=created.data["id"])
        self.assertEqual(skill.organization_id, self.organization.id)

        updated = self.client.patch(
            "/api/v1/apps/skills/storyboard/",
            {"description": "Updated"},
            format="json",
            **self.headers,
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["description"], "Updated")

    def test_removed_filesystem_skill_api_is_not_routable(self):
        response = self.client.get("/api/v1/apps/runtime-skills/", **self.headers)
        self.assertEqual(response.status_code, 404)

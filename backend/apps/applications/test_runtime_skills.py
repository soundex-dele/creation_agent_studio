from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.applications.models import Skill
from apps.applications.runtime_skills import (
    resolve_runtime_skills,
    skill_directory_for_adapter,
)
from modules.catalog.models import SkillDraft


class RuntimeSkillDiscoveryTest(SimpleTestCase):
    def test_uses_the_directory_for_the_configured_adapter(self):
        with (
            TemporaryDirectory() as codex_directory,
            TemporaryDirectory() as graphflow_directory,
        ):
            with override_settings(
                AGENT_ENGINE_ADAPTER="graphflow",
                CODEX_SKILLS_DIRECTORY=codex_directory,
                GRAPHFLOW_SKILLS_DIRECTORY=graphflow_directory,
            ):
                self.assertEqual(
                    skill_directory_for_adapter(),
                    Path(graphflow_directory).resolve(),
                )

    def test_rescans_skill_file_and_returns_its_latest_metadata(self):
        with TemporaryDirectory() as directory, override_settings(
            AGENT_ENGINE_ADAPTER="codex",
            CODEX_SKILLS_DIRECTORY=directory,
        ):
            skill_path = Path(directory) / "repo-audit" / "SKILL.md"
            skill_path.parent.mkdir()
            skill_path.write_text(
                "---\nname: repo-audit\ndescription: First description\n---\n",
                encoding="utf-8",
            )

            first = resolve_runtime_skills(["repo-audit"])
            skill_path.write_text(
                "---\nname: repo-audit\ndescription: Latest description\n---\n",
                encoding="utf-8",
            )
            latest = resolve_runtime_skills(["repo-audit"])

        self.assertEqual(first[0]["description"], "First description")
        self.assertEqual(latest[0]["description"], "Latest description")


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
        draft = SkillDraft.objects.get(skill=skill)
        self.assertEqual(draft.organization_id, self.organization.id)
        self.assertEqual(draft.version, 1)
        self.assertEqual(draft.content["manifest"], {"entrypoint": "SKILL.md"})

        updated = self.client.patch(
            "/api/v1/apps/skills/storyboard/",
            {"description": "Updated"},
            format="json",
            **self.headers,
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["description"], "Updated")

        definition_updated = self.client.patch(
            "/api/v1/apps/skills/storyboard/",
            {
                "source_uri": "https://example.invalid/storyboard-v2.git",
                "manifest": {"entrypoint": "skills/storyboard.py"},
            },
            format="json",
            **self.headers,
        )
        self.assertEqual(definition_updated.status_code, 200, definition_updated.data)
        draft.refresh_from_db()
        self.assertEqual(draft.version, 2)
        self.assertEqual(
            draft.content["source_uri"],
            "https://example.invalid/storyboard-v2.git",
        )
        self.assertEqual(
            draft.content["manifest"], {"entrypoint": "skills/storyboard.py"}
        )

    def test_removed_filesystem_skill_api_is_not_routable(self):
        response = self.client.get("/api/v1/apps/runtime-skills/", **self.headers)
        self.assertEqual(response.status_code, 404)

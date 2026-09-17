from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.agents.high_school_tutors import TUTOR_DEFINITIONS
from apps.agents.models import Agent, AgentCategory
from apps.enterprise.models import Organization
from apps.users.models import User
from modules.catalog.models import AgentDeployment, AgentDraft, AgentRevision


class HighSchoolTutorDefinitionsTest(TestCase):
    def test_definitions_cover_nine_unique_subjects_with_detailed_prompts(self):
        self.assertEqual(len(TUTOR_DEFINITIONS), 9)
        self.assertEqual(len({item.subject for item in TUTOR_DEFINITIONS}), 9)
        self.assertEqual(len({item.slug for item in TUTOR_DEFINITIONS}), 9)
        for definition in TUTOR_DEFINITIONS:
            self.assertGreater(len(definition.system_prompt), 3000)
            self.assertIn("提示阶梯", definition.system_prompt)
            self.assertIn("本学科专项教学规范", definition.system_prompt)


class ImportHighSchoolTutorsCommandTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="tutor-owner", password="p")
        self.organization = self.owner.owned_organizations.get()

    def test_imports_publishes_and_deploys_all_tutors_idempotently(self):
        output = StringIO()
        call_command(
            "import_high_school_tutors",
            organization=self.organization.slug,
            stdout=output,
        )

        agents = Agent.objects.filter(
            organization=self.organization,
            slug__startswith="high-school-",
        )
        self.assertEqual(agents.count(), 9)
        self.assertTrue(
            AgentCategory.objects.filter(slug="high-school-education").exists()
        )
        self.assertEqual(AgentDraft.objects.filter(agent__in=agents).count(), 9)
        self.assertEqual(AgentRevision.objects.filter(agent__in=agents).count(), 9)
        self.assertEqual(AgentDeployment.objects.filter(agent__in=agents).count(), 9)
        self.assertIn("共处理 9 个智能体", output.getvalue())

        draft_versions = dict(
            AgentDraft.objects.filter(agent__in=agents).values_list(
                "agent_id", "version"
            )
        )
        call_command(
            "import_high_school_tutors",
            organization=self.organization.slug,
            stdout=StringIO(),
        )

        self.assertEqual(
            Agent.objects.filter(
                organization=self.organization,
                slug__startswith="high-school-",
            ).count(),
            9,
        )
        self.assertEqual(AgentRevision.objects.filter(agent__in=agents).count(), 9)
        self.assertEqual(
            dict(
                AgentDraft.objects.filter(agent__in=agents).values_list(
                    "agent_id", "version"
                )
            ),
            draft_versions,
        )

    def test_can_import_selected_subjects(self):
        call_command(
            "import_high_school_tutors",
            organization=self.organization.slug,
            subjects=["math", "physics"],
            stdout=StringIO(),
        )

        self.assertEqual(
            set(
                Agent.objects.filter(
                    organization=self.organization,
                    slug__startswith="high-school-",
                ).values_list("slug", flat=True)
            ),
            {"high-school-math-tutor", "high-school-physics-tutor"},
        )

    def test_requires_organization_when_multiple_are_active(self):
        other_owner = User.objects.create_user(username="other-owner", password="p")
        Organization.objects.create(
            name="Other organization",
            slug="other-organization",
            owner=other_owner,
        )

        with self.assertRaisesMessage(CommandError, "--organization"):
            call_command("import_high_school_tutors", stdout=StringIO())

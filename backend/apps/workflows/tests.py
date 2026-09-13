from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from modules.catalog.models import (
    ApplicationDeployment,
    ApplicationDraft,
    ApplicationRevision,
    DeploymentEnvironment,
)
from modules.catalog.services import canonical_content_hash
from modules.execution.models import Run

from .models import Workflow


class WorkflowApiTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="workflow-owner")
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        category = ApplicationCategory.objects.create(name="Workflow apps", slug="workflow-apps")
        self.applications = []
        for index in range(2):
            application = Application.objects.create(
                category=category,
                name=f"App {index}",
                slug=f"workflow-app-{index}",
                description="Test",
                created_by=self.user,
                organization=self.organization,
                kind=Application.Kind.TASK,
            )
            content = {
                "kind": "task",
                "executor_kind": "media",
                "executor_key": "batch-transcribe",
                "renderer_key": "generic-task",
                "input_schema": {},
                "output_schema": {},
                "default_config": {},
            }
            ApplicationDraft.objects.create(
                organization=self.organization,
                application=application,
                updated_by=self.user,
                content=content,
            )
            revision = ApplicationRevision.objects.create(
                organization=self.organization,
                application=application,
                revision_no=1,
                content=content,
                content_hash=canonical_content_hash(content),
                created_by=self.user,
            )
            ApplicationDeployment.objects.create(
                organization=self.organization,
                application=application,
                environment=DeploymentEnvironment.PRODUCTION,
                revision=revision,
                updated_by=self.user,
            )
            self.applications.append(application)

    def test_start_creates_single_durable_run_with_step_snapshot(self):
        response = self.client.post("/api/v1/workflows/", {
            "name": "Content flow",
            "steps": [
                {
                    "key": "first", "application_id": self.applications[0].id,
                    "name": "First", "order": 0, "depends_on": [],
                },
                {
                    "key": "second", "application_id": self.applications[1].id,
                    "name": "Second", "order": 1, "depends_on": ["first"],
                    "max_attempts": 2,
                },
            ],
        }, format="json", **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        workflow = Workflow.objects.get(pk=response.data["id"])

        response = self.client.post(
            f"/api/v1/workflows/{workflow.id}/start/",
            {"input": {"folder": "example"}},
            format="json",
            HTTP_IDEMPOTENCY_KEY="workflow-run-1",
            **self.headers,
        )
        self.assertEqual(response.status_code, 202, response.data)
        run = Run.objects.get(pk=response.data["id"])
        self.assertEqual(run.executor_kind, Run.ExecutorKind.WORKFLOW)
        self.assertEqual(run.executor_key, "workflow-dag")
        self.assertEqual(len(run.definition_snapshot["workflow_steps"]), 2)
        self.assertEqual(
            run.definition_snapshot["workflow_steps"][1]["depends_on"], ["first"]
        )
        self.assertEqual(
            run.definition_snapshot["workflow_steps"][1]["max_attempts"], 2
        )

        replay = self.client.post(
            f"/api/v1/workflows/{workflow.id}/start/",
            {"input": {"folder": "example"}},
            format="json",
            HTTP_IDEMPOTENCY_KEY="workflow-run-1",
            **self.headers,
        )
        self.assertEqual(replay.status_code, 202, replay.data)
        self.assertEqual(replay.data["id"], response.data["id"])
        self.assertEqual(Run.objects.filter(source_type="workflow").count(), 1)

        workflow.steps.all().delete()
        run.refresh_from_db()
        self.assertEqual(len(run.definition_snapshot["workflow_steps"]), 2)

    def test_rejects_cyclic_workflow(self):
        response = self.client.post("/api/v1/workflows/", {
            "name": "Cycle",
            "steps": [
                {
                    "key": "first", "application_id": self.applications[0].id,
                    "name": "First", "order": 0, "depends_on": ["second"],
                },
                {
                    "key": "second", "application_id": self.applications[1].id,
                    "name": "Second", "order": 1, "depends_on": ["first"],
                },
            ],
        }, format="json", **self.headers)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("工作流依赖不能形成环", str(response.data))

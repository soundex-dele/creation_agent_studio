from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import (
    Application,
    ApplicationCategory,
    ChatApplication,
    Skill,
)
from apps.conversations.models import Conversation
from apps.enterprise.models import Membership
from modules.catalog.models import (
    AgentDraft,
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
        expected_workspace = (
            Path(settings.AGENT_WORKSPACE_ROOT)
            / "organizations" / str(self.organization.id)
            / "workflows" / str(run.id)
        ).resolve()
        self.assertEqual(Path(run.input["working_directory"]), expected_workspace)
        self.assertTrue(expected_workspace.is_dir())

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

    def test_owner_can_delete_workflow(self):
        workflow = Workflow.objects.create(
            organization=self.organization,
            owner=self.user,
            name="Disposable workflow",
            is_public=True,
        )

        listed = self.client.get("/api/v1/workflows/", **self.headers)
        self.assertEqual(listed.status_code, 200, listed.data)
        results = listed.data.get("results", listed.data)
        item = next(row for row in results if row["id"] == str(workflow.id))
        self.assertTrue(item["can_delete"])

        developer = get_user_model().objects.create_user(username="workflow-developer")
        Membership.objects.update_or_create(
            organization=self.organization,
            user=developer,
            defaults={"role": Membership.Role.DEVELOPER, "is_active": True},
        )
        self.client.force_authenticate(developer)
        listed = self.client.get("/api/v1/workflows/", **self.headers)
        results = listed.data.get("results", listed.data)
        item = next(row for row in results if row["id"] == str(workflow.id))
        self.assertFalse(item["can_delete"])
        denied = self.client.delete(
            f"/api/v1/workflows/{workflow.id}/",
            **self.headers,
        )
        self.assertEqual(denied.status_code, 403, denied.data)

        self.client.force_authenticate(self.user)
        deleted = self.client.delete(
            f"/api/v1/workflows/{workflow.id}/",
            **self.headers,
        )
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertFalse(Workflow.objects.filter(pk=workflow.id).exists())

    def test_manual_workflow_round_trips_and_cannot_start_automatically(self):
        chat_application = Application.objects.create(
            category=self.applications[0].category,
            name="Manual chat",
            slug="manual-workflow-chat",
            description="Manual chat step",
            created_by=self.user,
            organization=self.organization,
            kind=Application.Kind.CHAT,
        )
        chat_marker = ChatApplication.objects.create(application=chat_application)
        response = self.client.post("/api/v1/workflows/", {
            "name": "Manual content flow",
            "execution_mode": "manual",
            "steps": [{
                "key": "first",
                "application_id": chat_application.id,
                "name": "First",
                "order": 0,
                "depends_on": [],
            }],
        }, format="json", **self.headers)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["execution_mode"], "manual")

        detail = self.client.get(
            f"/api/v1/workflows/{response.data['id']}/",
            **self.headers,
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["execution_mode"], "manual")

        started = self.client.post(
            f"/api/v1/workflows/{response.data['id']}/start/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="manual-workflow-1",
            **self.headers,
        )
        self.assertEqual(started.status_code, 409, started.data)
        self.assertEqual(Run.objects.filter(source_type="workflow").count(), 0)

        with CaptureQueriesContext(connection) as queries:
            opened = self.client.post(
                f"/api/v1/workflows/{response.data['id']}/manual-session/",
                {"action": "open"},
                format="json",
                **self.headers,
            )
        self.assertEqual(opened.status_code, 201, opened.data)
        if connection.vendor == "sqlite":
            self.assertTrue(any(
                'UPDATE "workflows"' in query["sql"]
                and '"updated_at" = "workflows"."updated_at"' in query["sql"]
                for query in queries.captured_queries
            ))
        self.assertEqual(opened.data["status"], Run.Status.RUNNING)
        self.assertEqual(
            opened.data["definition_snapshot"]["execution_mode"], "manual"
        )

        reopened = self.client.post(
            f"/api/v1/workflows/{response.data['id']}/manual-session/",
            {"action": "open"},
            format="json",
            **self.headers,
        )
        self.assertEqual(reopened.data["id"], opened.data["id"])
        self.assertEqual(Run.objects.filter(source_type="workflow").count(), 1)

        conversation = Conversation.objects.create(
            user=self.user,
            organization=self.organization,
            chat_application=chat_marker,
            title="Manual workflow conversation",
        )
        attached = self.client.post(
            f"/api/v1/workflows/{response.data['id']}/manual-session/",
            {
                "action": "attach_conversation",
                "run_id": opened.data["id"],
                "step_key": "first",
                "conversation_id": conversation.id,
            },
            format="json",
            **self.headers,
        )
        self.assertEqual(attached.status_code, 200, attached.data)
        self.assertEqual(
            attached.data["output_summary"]["conversations"]["first"],
            str(conversation.id),
        )

        completed = self.client.post(
            f"/api/v1/workflows/{response.data['id']}/manual-session/",
            {"action": "complete", "run_id": opened.data["id"]},
            format="json",
            **self.headers,
        )
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["status"], Run.Status.SUCCEEDED)

    def test_start_freezes_chat_application_draft_without_deployment(self):
        agent_category = AgentCategory.objects.create(
            name="Workflow agents", slug="workflow-agents"
        )
        agent = Agent.objects.create(
            category=agent_category,
            name="Draft writer",
            slug="workflow-draft-writer",
            description="Writes from a draft",
            created_by=self.user,
            organization=self.organization,
        )
        agent_definition = {
            "system_prompt": "Write a useful article.",
            "model_config": {},
            "tool_config": [],
            "knowledge_config": [],
            "guardrail_config": {},
            "workflow_config": {},
            "skill_bindings": [],
        }
        AgentDraft.objects.create(
            organization=self.organization,
            agent=agent,
            updated_by=self.user,
            content=agent_definition,
        )
        application = Application.objects.create(
            category=self.applications[0].category,
            name="Draft chat app",
            slug="workflow-draft-chat",
            description="Chat app without a production deployment",
            created_by=self.user,
            organization=self.organization,
            kind=Application.Kind.CHAT,
        )
        ChatApplication.objects.create(application=application)
        skill = Skill.objects.create(
            organization=self.organization,
            owner=self.user,
            slug="workflow-draft-skill",
            name="Workflow draft skill",
            visibility=Skill.Visibility.ORGANIZATION,
        )
        draft = ApplicationDraft.objects.create(
            organization=self.organization,
            application=application,
            updated_by=self.user,
            content={
                "kind": "chat",
                "executor_kind": "agent",
                "executor_key": "agent-chat",
                "renderer_key": "chat",
                "retry_policy": {"max_attempts": 3, "retry_safe": True},
                "default_config": {},
                "agent_bindings": [{
                    "agent_id": agent.id,
                    "label": agent.name,
                    "is_default": True,
                    "config_overrides": {},
                    "order": 0,
                }],
                "skill_bindings": [{
                    "skill_id": str(skill.id),
                    "mode": "required",
                    "config": {},
                    "order": 0,
                }],
                "guided_prompts": [],
            },
        )
        workflow_response = self.client.post("/api/v1/workflows/", {
            "name": "Draft chat flow",
            "steps": [{
                "key": "write",
                "application_id": application.id,
                "name": "Write",
                "order": 0,
                "depends_on": [],
            }],
        }, format="json", **self.headers)
        self.assertEqual(workflow_response.status_code, 201, workflow_response.data)

        runtime_skills = [{
            "name": skill.slug,
            "display_name": skill.name,
            "path": "/skills/workflow-draft-skill/SKILL.md",
            "adapter": "codex",
        }]
        with patch(
            "apps.workflows.views.resolve_runtime_skills",
            return_value=runtime_skills,
        ):
            response = self.client.post(
                f"/api/v1/workflows/{workflow_response.data['id']}/start/",
                format="json",
                HTTP_IDEMPOTENCY_KEY="workflow-draft-chat-1",
                **self.headers,
            )

        self.assertEqual(response.status_code, 202, response.data)
        run = Run.objects.get(pk=response.data["id"])
        step = run.definition_snapshot["workflow_steps"][0]
        self.assertEqual(step["executor_kind"], "agent")
        self.assertEqual(step["executor_key"], "agent-completion")
        self.assertEqual(step["application_draft_id"], str(draft.id))
        self.assertEqual(step["application_draft_version"], draft.version)
        self.assertEqual(step["content"]["skill_bindings"], [])
        self.assertEqual(step["skill_revisions"], [])
        self.assertEqual(step["runtime_input"]["skills"], runtime_skills)
        self.assertNotIn("conversation_id", step)
        self.assertFalse(
            Conversation.objects.filter(process_id="workflow:write").exists()
        )

        from modules.execution.runtime import builtin

        def finish_child(_root, children, _sink, _organization_id, **_kwargs):
            return {
                "write": {
                    "status": "completed",
                    "attempts": 1,
                    "output": {"result": "Draft article"},
                    "child_run_id": str(children["write"]),
                }
            }

        result_sink = MagicMock(cancelled=False)
        with patch.object(builtin, "_wait_for_step_runs", side_effect=finish_child):
            result = builtin.execute_workflow({
                "run_id": str(run.id),
                "organization_id": str(self.organization.id),
                "definition_snapshot": run.definition_snapshot,
                "input": run.input,
            }, result_sink)

        self.assertEqual(result["status"], "completed")
        child = run.child_runs.get(node_key="write")
        conversation = Conversation.objects.get(
            pk=child.definition_snapshot["conversation_id"],
            chat_application_id=application.id,
        )
        self.assertEqual(conversation.title, "Draft chat flow · Write")
        self.assertEqual(conversation.process_id, "workflow:write")
        self.assertEqual(
            conversation.working_directory,
            run.input["working_directory"],
        )
        started_payload = next(
            call.args[1]
            for call in result_sink.emit.call_args_list
            if call.args[0] == "workflow.step.started"
        )
        self.assertEqual(
            started_payload["conversation_id"],
            str(conversation.id),
        )
        self.assertEqual(
            step["content"]["dependencies"]["agents"][0]["definition"],
            agent_definition,
        )
        self.assertFalse(
            ApplicationDeployment.objects.filter(application=application).exists()
        )

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

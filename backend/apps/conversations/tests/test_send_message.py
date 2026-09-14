from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.conversations.models import Conversation, Message
from modules.catalog.models import AgentDeployment, AgentRevision
from modules.catalog.services import canonical_content_hash
from modules.execution.application.projections import (
    project_input_accepted,
    project_input_required,
    project_terminal_run,
)
from modules.execution.models import Run, RunEvent


class DurableConversationRunTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="chat-user")
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        category, _ = AgentCategory.objects.get_or_create(
            slug="conversation-tests",
            defaults={"name": "Conversation tests"},
        )
        self.agent = Agent.objects.create(
            category=category,
            name="Conversation agent",
            slug="conversation-agent",
            description="Test Agent",
            is_public=False,
            created_by=self.user,
            organization=self.organization,
        )
        definition = {"system_prompt": "You are a test agent."}
        revision = AgentRevision.objects.create(
            organization=self.organization,
            agent=self.agent,
            revision_no=1,
            content=definition,
            content_hash=canonical_content_hash(definition),
            created_by=self.user,
        )
        AgentDeployment.objects.create(
            organization=self.organization,
            agent=self.agent,
            environment="production",
            revision=revision,
            updated_by=self.user,
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            organization=self.organization,
            title="Chat",
            agent=self.agent,
        )

    def test_send_message_creates_run_instead_of_synchronous_execution(self):
        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "hello"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-message-1",
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

    @patch("apps.conversations.views.start_agent_run")
    def test_failed_run_creation_does_not_persist_user_message(self, start_run):
        from modules.execution.application.errors import DeploymentUnavailable

        start_run.side_effect = DeploymentUnavailable(
            "Agent has no production deployment"
        )

        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "must roll back"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-message-failure",
            **self.headers,
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(Message.objects.filter(
            conversation=self.conversation,
            role="user",
            content="must roll back",
        ).exists())

    def test_idempotent_replay_does_not_duplicate_user_message(self):
        url = f"/api/v1/conversations/{self.conversation.id}/send_message/"
        first = self.client.post(
            url,
            {"content": "hello once"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-replay",
            **self.headers,
        )
        replay = self.client.post(
            url,
            {"content": "hello once"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-replay",
            **self.headers,
        )

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(replay.status_code, 202, replay.data)
        self.assertEqual(first.data["id"], replay.data["id"])
        self.assertEqual(replay["Idempotent-Replay"], "true")
        self.assertEqual(Message.objects.filter(
            conversation=self.conversation,
            role="user",
            content="hello once",
        ).count(), 1)

    def test_send_message_requires_client_idempotency_key(self):
        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "hello"},
            format="json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.filter(
            conversation=self.conversation,
            role="user",
        ).count(), 0)

    def test_send_message_carries_existing_agent_thread(self):
        self.conversation.agent_thread_provider = "codex"
        self.conversation.agent_thread_id = "thread-1"
        self.conversation.save(update_fields=(
            "agent_thread_provider", "agent_thread_id",
        ))

        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "continue"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-thread-resume",
            **self.headers,
        )

        self.assertEqual(response.status_code, 202, response.data)
        run = Run.objects.get(pk=response.data["id"])
        self.assertEqual(run.input["agent_thread"], {
            "provider": "codex",
            "id": "thread-1",
        })

    def test_conversation_detail_exposes_active_run_for_refresh_recovery(self):
        sent = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "wait for my answer"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-refresh-recovery",
            **self.headers,
        )

        detail = self.client.get(
            f"/api/v1/conversations/{self.conversation.id}/",
            **self.headers,
        )

        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["organization_id"], str(self.organization.id))
        self.assertEqual(detail.data["active_run"]["id"], sent.data["id"])
        self.assertEqual(detail.data["active_run"]["source_type"], "conversation")

    def test_send_message_applies_agent_and_skill_composer_selection(self):
        selected_agent = Agent.objects.create(
            category=self.agent.category,
            name="Selected agent",
            slug="selected-agent",
            description="Selected by the composer",
            is_public=False,
            created_by=self.user,
            organization=self.organization,
        )
        definition = {"system_prompt": "Use the selected agent instructions."}
        revision = AgentRevision.objects.create(
            organization=self.organization,
            agent=selected_agent,
            revision_no=1,
            content=definition,
            content_hash=canonical_content_hash(definition),
            created_by=self.user,
        )
        AgentDeployment.objects.create(
            organization=self.organization,
            agent=selected_agent,
            environment="production",
            revision=revision,
            updated_by=self.user,
        )
        self.conversation.agent_thread_provider = "codex"
        self.conversation.agent_thread_id = "thread-1"
        self.conversation.save(update_fields=(
            "agent_thread_provider", "agent_thread_id",
        ))

        with TemporaryDirectory() as directory, override_settings(
            AGENT_ENGINE_ADAPTER="codex",
            CODEX_SKILLS_DIRECTORY=directory,
        ):
            skill_path = Path(directory) / "repo-audit" / "SKILL.md"
            skill_path.parent.mkdir()
            skill_path.write_text(
                "---\nname: repo-audit\ndescription: Audit a repository\n---\n",
                encoding="utf-8",
            )
            response = self.client.post(
                f"/api/v1/conversations/{self.conversation.id}/send_message/",
                {
                    "content": "inspect this repository",
                    "agent_id": selected_agent.id,
                    "skill_names": ["repo-audit"],
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY="conversation-composer-selection",
                **self.headers,
            )

        self.assertEqual(response.status_code, 202, response.data)
        run = Run.objects.get(pk=response.data["id"])
        self.assertEqual(run.definition_snapshot["agent_id"], str(selected_agent.id))
        self.assertEqual(
            run.definition_snapshot["agent_definition"]["system_prompt"],
            "Use the selected agent instructions.",
        )
        self.assertEqual(run.input["agent_thread"], {
            "provider": "codex",
            "id": "thread-1",
        })
        self.assertEqual(run.input["skills"], [{
            "name": "repo-audit",
            "display_name": "repo-audit",
            "description": "Audit a repository",
            "path": str(skill_path.resolve()),
            "adapter": "codex",
        }])
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.agent_id, selected_agent.id)
        message = Message.objects.get(
            conversation=self.conversation,
            role="user",
            content="inspect this repository",
        )
        self.assertEqual(message.metadata["composer"], {
            "agent_id": selected_agent.id,
            "skill_names": ["repo-audit"],
            "skills": ["repo-audit"],
        })

    def test_missing_adapter_directory_skill_is_rejected(self):
        with TemporaryDirectory() as directory, override_settings(
            AGENT_ENGINE_ADAPTER="codex",
            CODEX_SKILLS_DIRECTORY=directory,
        ):
            response = self.client.post(
                f"/api/v1/conversations/{self.conversation.id}/send_message/",
                {"content": "use it", "skill_names": ["missing-skill"]},
                format="json",
                HTTP_IDEMPOTENCY_KEY="conversation-missing-skill-path",
                **self.headers,
            )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("missing-skill", str(response.data["skill_names"]))

    def test_composer_options_reads_current_global_adapter_directory(self):
        with TemporaryDirectory() as directory, override_settings(
            AGENT_ENGINE_ADAPTER="graphflow",
            GRAPHFLOW_SKILLS_DIRECTORY=directory,
        ):
            skill_path = Path(directory) / "design" / "SKILL.md"
            skill_path.parent.mkdir()
            skill_path.write_text(
                "---\nname: design\ndescription: Current design skill\n---\n",
                encoding="utf-8",
            )

            response = self.client.get(
                "/api/v1/conversations/composer-options/",
                **self.headers,
            )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["adapter"], "graphflow")
        self.assertEqual(response.data["skills"], [{
            "name": "design",
            "display_name": "design",
            "description": "Current design skill",
            "path": str(skill_path.resolve()),
            "adapter": "graphflow",
        }])

    def test_rejects_a_second_turn_while_conversation_run_is_active(self):
        first = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "first"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-active-first",
            **self.headers,
        )
        second = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "second"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-active-second",
            **self.headers,
        )

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 409, second.data)
        self.assertEqual(Message.objects.filter(
            conversation=self.conversation,
            role="user",
        ).count(), 1)

    def test_clear_removes_messages_and_agent_thread(self):
        self.conversation.agent_thread_provider = "codex"
        self.conversation.agent_thread_id = "thread-1"
        self.conversation.save(update_fields=(
            "agent_thread_provider", "agent_thread_id",
        ))
        Message.objects.create(
            conversation=self.conversation,
            role="user",
            content="clear me",
        )

        response = self.client.delete(
            f"/api/v1/conversations/{self.conversation.id}/clear/",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.agent_thread_provider, "")
        self.assertEqual(self.conversation.agent_thread_id, "")
        self.assertFalse(self.conversation.messages.exists())

    def test_terminal_projection_preserves_tool_history(self):
        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "inspect a file"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-tool-history",
            **self.headers,
        )
        run = Run.objects.get(pk=response.data["id"])
        RunEvent.objects.create(
            organization=self.organization,
            run=run,
            sequence=2,
            type="tool.started",
            payload={
                "tool_call_id": "call-1",
                "name": "read_file",
                "input": {"path": "notes.txt"},
            },
        )
        RunEvent.objects.create(
            organization=self.organization,
            run=run,
            sequence=3,
            type="tool.completed",
            payload={
                "tool_call_id": "call-1",
                "name": "read_file",
                "result": {"lines": 3},
            },
        )

        project_terminal_run(run.id, {
            "result": "done",
            "model": "test-model",
            "usage": {"total_tokens": 4},
            "loaded_skills": ["Repository Audit"],
            "agent_thread": {"provider": "codex", "id": "thread-1"},
        })

        message = Message.objects.get(run=run)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.agent_thread_provider, "codex")
        self.assertEqual(self.conversation.agent_thread_id, "thread-1")
        self.assertEqual(message.content, "done")
        self.assertEqual(message.metadata["agent"]["tool_calls"], [{
            "id": "call-1",
            "name": "read_file",
            "status": "completed",
            "input": '{"path": "notes.txt"}',
            "result": '{"lines": 3}',
        }])
        self.assertEqual(
            message.metadata["agent"]["loaded_skills"], ["Repository Audit"])

    def test_interactive_run_projects_each_question_and_answer_as_messages(self):
        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "build an app"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-interactive-history",
            **self.headers,
        )
        run = Run.objects.get(pk=response.data["id"])
        RunEvent.objects.create(
            organization=self.organization,
            run=run,
            sequence=2,
            type="output.delta",
            payload={"text": "I need one detail."},
        )
        required = RunEvent.objects.create(
            organization=self.organization,
            run=run,
            sequence=3,
            type="input.required",
            payload={
                "input_request_id": "question-1",
                "input_kind": "answer",
                "questions": [{
                    "id": "framework",
                    "header": "Framework",
                    "question": "Which framework?",
                    "options": [
                        {"label": "React", "value": "React"},
                        {"label": "Vue", "value": "Vue"},
                    ],
                }],
            },
        )
        accepted = RunEvent.objects.create(
            organization=self.organization,
            run=run,
            sequence=4,
            type="input.accepted",
            payload={"input_request_id": "question-1"},
        )
        command = SimpleNamespace(
            input_request_id="question-1",
            type="answer",
            payload={"answers": {"framework": {"answers": ["React"]}}},
        )

        question_message = project_input_required(run.id, required)
        answer_message = project_input_accepted(run.id, accepted, command)
        project_input_required(run.id, required)
        project_input_accepted(run.id, accepted, command)

        self.assertEqual(question_message.role, "assistant")
        self.assertEqual(
            question_message.content,
            "I need one detail.\n\n**Framework**\nWhich framework?\n可选：React / Vue",
        )
        self.assertEqual(answer_message.role, "user")
        self.assertEqual(answer_message.content, "React")
        self.assertEqual(
            list(run.projected_messages.order_by("run_event_sequence").values_list(
                "run_event_sequence", "role",
            )),
            [(3, "assistant"), (4, "user")],
        )

    def test_detail_repairs_a_missing_terminal_message(self):
        response = self.client.post(
            f"/api/v1/conversations/{self.conversation.id}/send_message/",
            {"content": "finish this"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="conversation-terminal-repair",
            **self.headers,
        )
        run = Run.objects.get(pk=response.data["id"])
        run.status = Run.Status.SUCCEEDED
        run.next_event_sequence = 2
        run.output_summary = {
            "result": "Recovered final answer",
            "model": "codex-default",
            "usage": {},
        }
        run.save(update_fields=("status", "next_event_sequence", "output_summary"))
        RunEvent.objects.create(
            organization=self.organization,
            run=run,
            sequence=2,
            type="run.succeeded",
            payload={},
        )

        detail = self.client.get(
            f"/api/v1/conversations/{self.conversation.id}/",
            **self.headers,
        )

        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertTrue(Message.objects.filter(
            run=run,
            run_event_sequence=2,
            role="assistant",
            content="Recovered final answer",
        ).exists())

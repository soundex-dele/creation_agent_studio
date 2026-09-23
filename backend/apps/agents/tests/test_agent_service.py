"""Tests for the Agent engine and its sole durable Run adapter."""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.test.utils import override_settings

from apps.users.models import User
from core.agent_engine.models import LLMResponse, TokenUsage
from core.llm.factory import build_agent_engine
from apps.agents.execution import execute_agent_completion


class BuildAgentEngineTest(TestCase):
    @override_settings(GRAPHFLOW_API_KEY="key-123", GRAPHFLOW_BASE_URL="https://example.com/v1")
    def test_builds_engine_from_settings(self):
        self.assertIsNotNone(build_agent_engine())


class DurableAgentAdapterTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.organization = self.user.owned_organizations.get()

    @staticmethod
    def _payload(organization_id):
        return {
            "organization_id": str(organization_id),
            "definition_snapshot": {"agent_definition": {
                "system_prompt": "sys", "model_config": {},
            }},
            "input": {"message": "hi"},
        }

    @patch("apps.agents.execution.build_agent_engine")
    def test_success_returns_normalized_output(self, mock_factory):
        engine = MagicMock()
        engine.complete.return_value = LLMResponse(
            content="hello", usage=TokenUsage(), model="deepseek-chat"
        )
        mock_factory.return_value = engine
        sink = MagicMock(cancelled=False)
        output = execute_agent_completion(self._payload(self.organization.id), sink)
        self.assertEqual(output["result"], "hello")
        self.assertEqual(output["model"], "deepseek-chat")
        sink.emit.assert_any_call("output.delta", {"text": "hello"})

    @patch("apps.agents.execution.build_agent_engine")
    def test_codex_receives_image_paths(self, mock_factory):
        engine = MagicMock()
        engine.adapter_name = "codex"
        engine.complete.return_value = LLMResponse(
            content="described", usage=TokenUsage(), model="codex-default"
        )
        mock_factory.return_value = engine
        payload = self._payload(self.organization.id)
        payload["input"]["attachments"] = [{
            "path": "/tmp/example.png",
            "content_type": "image/png",
        }]

        execute_agent_completion(payload, MagicMock(cancelled=False))

        self.assertEqual(
            engine.complete.call_args.kwargs["image_paths"],
            ["/tmp/example.png"],
        )

    @patch("apps.agents.execution.build_agent_engine")
    def test_graphflow_rejects_image_paths(self, mock_factory):
        engine = MagicMock()
        engine.adapter_name = "graphflow"
        mock_factory.return_value = engine
        payload = self._payload(self.organization.id)
        payload["input"]["attachments"] = [{"path": "/tmp/example.png"}]

        with self.assertRaisesMessage(RuntimeError, "GraphFlow"):
            execute_agent_completion(payload, MagicMock(cancelled=False))

        engine.complete.assert_not_called()

    @patch("apps.agents.execution.build_agent_engine")
    def test_forwards_streaming_and_tool_events_without_duplicate_final_delta(
        self, mock_factory
    ):
        engine = MagicMock()

        def complete(_messages, **options):
            options["on_event"]("output.delta", {"text": "hel"})
            options["on_event"]("tool.started", {
                "tool_call_id": "call-1", "name": "read_file", "input": {"path": "a"},
            })
            options["on_event"]("tool.completed", {
                "tool_call_id": "call-1", "name": "read_file", "result": "ok",
            })
            options["on_event"]("output.delta", {"text": "lo"})
            return LLMResponse(
                content="hello", usage=TokenUsage(), model="deepseek-chat"
            )

        engine.complete.side_effect = complete
        mock_factory.return_value = engine
        sink = MagicMock(cancelled=False)

        execute_agent_completion(self._payload(self.organization.id), sink)

        self.assertEqual([item.args for item in sink.emit.call_args_list[:4]], [
            ("output.delta", {"text": "hel"}),
            ("tool.started", {
                "tool_call_id": "call-1", "name": "read_file", "input": {"path": "a"},
            }),
            ("tool.completed", {
                "tool_call_id": "call-1", "name": "read_file", "result": "ok",
            }),
            ("output.delta", {"text": "lo"}),
        ])
        delta_calls = [
            call for call in sink.emit.call_args_list if call.args[0] == "output.delta"
        ]
        self.assertEqual(len(delta_calls), 2)

    @patch("apps.agents.execution.build_agent_engine")
    def test_coalesces_tiny_streaming_deltas(self, mock_factory):
        engine = MagicMock()
        content = "x" * 2048

        def complete(_messages, **options):
            for character in content:
                options["on_event"]("output.delta", {"text": character})
            return LLMResponse(
                content=content, usage=TokenUsage(), model="deepseek-chat"
            )

        engine.complete.side_effect = complete
        mock_factory.return_value = engine
        sink = MagicMock(cancelled=False)

        execute_agent_completion(self._payload(self.organization.id), sink)

        delta_calls = [
            call for call in sink.emit.call_args_list if call.args[0] == "output.delta"
        ]
        self.assertEqual(
            "".join(call.args[1]["text"] for call in delta_calls), content
        )
        self.assertLessEqual(len(delta_calls), 9)

    @patch("apps.agents.execution.build_agent_engine")
    def test_failure_raises_for_coordinator(self, mock_factory):
        mock_factory.return_value.complete.return_value = LLMResponse(
            content="", usage=TokenUsage(), model="deepseek-chat",
            success=False, error="boom",
        )
        with self.assertRaisesMessage(RuntimeError, "boom"):
            execute_agent_completion(
                self._payload(self.organization.id), MagicMock(cancelled=False)
            )

    @patch("apps.agents.execution.build_agent_engine")
    def test_cancelled_provider_error_returns_for_cancelled_outcome(self, mock_factory):
        mock_factory.return_value.complete.side_effect = RuntimeError("interrupted")
        sink = MagicMock(cancelled=True)

        output = execute_agent_completion(self._payload(self.organization.id), sink)

        self.assertEqual(output, {})
        self.assertTrue(callable(
            mock_factory.return_value.complete.call_args.kwargs["cancelled"]
        ))

    @patch("apps.agents.execution.build_agent_engine")
    def test_success_serializes_usage(self, mock_factory):
        mock_factory.return_value.complete.return_value = LLMResponse(
            content="hello",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            model="deepseek-chat",
        )
        output = execute_agent_completion(
            self._payload(self.organization.id), MagicMock(cancelled=False)
        )
        self.assertEqual(output["usage"]["total_tokens"], 8)

    @patch("apps.agents.execution.build_agent_engine")
    def test_reuses_and_returns_provider_thread(self, mock_factory):
        engine = MagicMock()
        engine.adapter_name = "codex"
        engine.complete.return_value = LLMResponse(
            content="continued",
            usage=TokenUsage(),
            model="codex-default",
            thread_id="thread-1",
        )
        mock_factory.return_value = engine
        payload = self._payload(self.organization.id)
        payload["input"]["agent_thread"] = {
            "provider": "codex",
            "id": "thread-1",
        }

        output = execute_agent_completion(
            payload, MagicMock(cancelled=False)
        )

        self.assertEqual(engine.complete.call_args.kwargs["thread_id"], "thread-1")
        self.assertEqual(output["agent_thread"], {
            "provider": "codex",
            "id": "thread-1",
        })

    @patch("apps.agents.execution.build_agent_engine")
    def test_resumes_codex_thread_with_structured_question_answers(self, mock_factory):
        engine = MagicMock()
        engine.adapter_name = "codex"
        engine.complete.return_value = LLMResponse(
            content="continued",
            usage=TokenUsage(),
            model="codex-default",
            thread_id="thread-1",
        )
        mock_factory.return_value = engine
        payload = self._payload(self.organization.id)
        payload["input"].update(permission_mode="allow_all", collaboration_mode="plan")
        payload["checkpoint"] = {"metadata": {"checkpoint": {
            "messages": [{"role": "user", "content": "Build the app"}],
            "agent_thread": {"provider": "codex", "id": "thread-1"},
            "input_request": {"questions": [
                {"id": "framework", "question": "Which framework?"},
                {"id": "theme", "question": "Which theme?"},
            ]},
        }}}
        payload["resume_command"] = {
            "type": "answer",
            "payload": {"answers": {
                "framework": {"answers": ["React"]},
                "theme": {"answers": ["Dark"]},
            }},
        }

        execute_agent_completion(payload, MagicMock(cancelled=False))

        self.assertEqual(engine.complete.call_args.kwargs["thread_id"], "thread-1")
        self.assertEqual(engine.complete.call_args.kwargs["permission_mode"], "allow_all")
        self.assertEqual(engine.complete.call_args.kwargs["collaboration_mode"], "plan")
        self.assertEqual(engine.complete.call_args.args[0][-1], {
            "role": "user",
            "content": (
                "Answers to the questions you asked:\n"
                "- Which framework?: React\n"
                "- Which theme?: Dark\n"
                "Continue the previous task using these answers."
            ),
        })

    @patch("apps.agents.execution.build_agent_engine")
    def test_checkpoints_request_user_input_metadata(self, mock_factory):
        engine = MagicMock()
        engine.adapter_name = "codex"
        request = {
            "input_kind": "answer",
            "kind": "question",
            "questions": [{"id": "framework", "question": "Which framework?"}],
        }
        engine.complete.return_value = LLMResponse(
            content="",
            usage=TokenUsage(),
            model="codex-default",
            input_request=request,
            thread_id="thread-1",
        )
        mock_factory.return_value = engine
        sink = MagicMock(cancelled=False)

        execute_agent_completion(self._payload(self.organization.id), sink)

        checkpoint = sink.request_input.call_args.kwargs["checkpoint"]
        self.assertEqual(checkpoint["input_request"], request)
        self.assertEqual(checkpoint["agent_thread"], {
            "provider": "codex",
            "id": "thread-1",
        })

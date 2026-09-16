import sys
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from core.agent_engine.models import LLMResponse, TokenUsage
from modules.execution.runtime import builtin
from app_center.batch_transcribe import runtime as batch_transcribe
from app_center.creation_master.backend import runtime as creation_master
from apps.agents.execution import execute_agent_completion
from apps.conversations.models import Conversation, Message
from apps.conversations.serializers import ConversationDetailSerializer
from modules.execution.application.projections import project_terminal_run
from modules.execution.application.runs import create_run, mirror_child_output_event
from modules.execution.models import Run


class _Sink:
    def __init__(self):
        self.events = []
        self.artifacts = []

    @property
    def cancelled(self):
        return False

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))

    def create_artifact(self, **artifact):
        self.artifacts.append(artifact)


class _SuspendSink(_Sink):
    def request_input(self, **request):
        self.request = request
        raise RuntimeError("suspended")


def test_creation_master_trim_decodes_ffmpeg_output_as_utf8(monkeypatch, tmp_path):
    source = tmp_path / "视频.mp4"
    source.write_bytes(b"")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="10\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(creation_master.subprocess, "run", fake_run)

    result = creation_master.execute_creation_master(
        {
            "allowed_roots": [str(tmp_path)],
            "input": {
                "operation": "trim",
                "folder": str(tmp_path),
                "trim_start": 1,
                "trim_end": 1,
            },
        },
        _Sink(),
    )

    assert result["total"] == 1
    assert len(calls) == 2
    assert all(kwargs["encoding"] == "utf-8" for _command, kwargs in calls)
    assert all(kwargs["errors"] == "replace" for _command, kwargs in calls)


def test_batch_transcribe_uses_durable_event_protocol(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "ignore.txt").write_text("ignore")
    seen = {}

    class FakeWhisperModel:
        def __init__(self, model):
            seen["model"] = model

        def transcribe(self, video, language=None):
            seen["video"] = video
            seen["language"] = language
            return [SimpleNamespace(text="hello")], SimpleNamespace(language="zh")

    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel)
    )
    sink = _Sink()

    result = batch_transcribe.execute_batch_transcribe(
        {
            "allowed_roots": [str(tmp_path)],
            "input": {
                "folder": str(tmp_path),
                "model": "tiny",
                "language": "zh",
            }
        },
        sink,
    )

    assert seen["video"].endswith("a.mp4")
    assert seen["model"] == "tiny"
    assert seen["language"] == "zh"
    assert [event_type for event_type, _ in sink.events] == [
        "tool.started",
        "tool.completed",
        "progress.updated",
    ]
    assert result["status"] == "completed"
    assert len(result["files"]) == 1
    assert sink.artifacts[0]["kind"] == "transcript"
    assert sink.artifacts[0]["filename"] == "a.txt"
    assert sink.artifacts[0]["content"] == b"hello\n"


def test_batch_transcribe_rejects_output_outside_runtime_roots(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    with pytest.raises(PermissionError, match="output is outside runtime roots"):
        batch_transcribe.execute_batch_transcribe(
            {
                "allowed_roots": [str(allowed)],
                "input": {
                    "folder": str(allowed),
                    "output_dir": str(outside),
                },
            },
            _Sink(),
        )


@pytest.mark.django_db(transaction=True)
def test_durable_workflow_creates_reusable_child_runs(monkeypatch):
    actor = get_user_model().objects.create_user(username="durable-dag-owner")
    organization = actor.owned_organizations.get()
    root = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        source_id="dag-1",
        definition_snapshot={},
        input_data={"topic": "durable"},
    )
    steps = [
        {
            "id": "step-1", "key": "first", "name": "First",
            "depends_on": [], "condition": {}, "max_attempts": 2,
            "application_id": 1, "application_revision_id": "revision-1",
            "application_content_hash": "a" * 64,
            "executor_kind": "media", "executor_key": "batch-transcribe",
            "content": {"retry_policy": {"retry_safe": True}},
            "effective_config": {},
        },
        {
            "id": "step-2", "key": "second", "name": "Second",
            "depends_on": ["first"], "condition": {}, "max_attempts": 1,
            "application_id": 2, "application_revision_id": "revision-2",
            "application_content_hash": "b" * 64,
            "executor_kind": "agent", "executor_key": "agent-completion",
            "content": {}, "effective_config": {},
            "runtime_input": {"skills": [{"name": "article-writer"}]},
        },
    ]

    def finish_children(_root, children, _sink, _organization_id, poll_interval=0.25):
        return {
            key: {
                "status": "completed", "attempts": 1,
                "output": {"node": key}, "child_run_id": str(child_id),
            }
            for key, child_id in children.items()
        }

    monkeypatch.setattr(builtin, "_wait_for_step_runs", finish_children)
    sink = _Sink()
    payload = {
        "run_id": str(root.id),
        "organization_id": str(organization.id),
        "definition_snapshot": {
            "durable_children": True,
            "workflow_steps": steps,
            "governance": {"require_tool_approval": True},
        },
        "input": {"topic": "durable"},
    }

    first_result = builtin.execute_workflow(payload, sink)
    second_result = builtin.execute_workflow(payload, _Sink())

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert root.child_runs.count() == 2
    first = root.child_runs.get(node_key="first")
    second = root.child_runs.get(node_key="second")
    assert first.executor_kind == Run.ExecutorKind.MEDIA
    assert first.max_attempts == 2
    assert second.executor_kind == Run.ExecutorKind.AGENT
    assert second.input["dependency_outputs"]["first"] == {"node": "first"}
    assert second.input["skills"] == [{"name": "article-writer"}]
    assert second.definition_snapshot["governance"]["require_tool_approval"] is True


@pytest.mark.django_db(transaction=True)
def test_durable_workflow_renders_guided_prompt_from_workflow_and_step_outputs(monkeypatch):
    actor = get_user_model().objects.create_user(username="guided-dag-owner")
    organization = actor.owned_organizations.get()
    root = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        source_id="guided-dag",
        definition_snapshot={},
        input_data={"topic": "AI productivity"},
    )
    prompt = {
        "key": "write",
        "prompt_template": "Topic: {source}\nMode: {mode}",
        "questions": [
            {"key": "source", "label": "Source", "type": "text", "required": True},
            {
                "key": "mode", "label": "Mode", "type": "single_choice",
                "required": True, "default_value": "full",
                "options": [{"value": "full", "label": "Full article"}],
            },
        ],
    }
    steps = [
        {
            "id": "step-1", "key": "writer", "name": "Writer",
            "depends_on": [], "condition": {}, "max_attempts": 1,
            "application_id": 1, "application_revision_id": "",
            "application_content_hash": "a" * 64,
            "executor_kind": "agent", "executor_key": "agent-completion",
            "content": {"guided_prompts": [prompt]},
            "effective_config": {
                "automation": {
                    "guided_prompt_key": "write",
                    "answers": {"source": {"from": "workflow.input.topic"}},
                }
            },
        },
        {
            "id": "step-2", "key": "layout", "name": "Layout",
            "depends_on": ["writer"], "condition": {}, "max_attempts": 1,
            "application_id": 2, "application_revision_id": "",
            "application_content_hash": "b" * 64,
            "executor_kind": "agent", "executor_key": "agent-completion",
            "content": {"guided_prompts": [prompt]},
            "effective_config": {
                "automation": {
                    "guided_prompt_key": "write",
                    "answers": {"source": {"from": "steps.writer.output.result"}},
                }
            },
        },
    ]

    def finish_children(_root, children, _sink, _organization_id, poll_interval=0.25):
        return {
            key: {
                "status": "completed", "attempts": 1,
                "output": {"result": "Rendered article" if key == "writer" else "Done"},
                "child_run_id": str(child_id),
            }
            for key, child_id in children.items()
        }

    monkeypatch.setattr(builtin, "_wait_for_step_runs", finish_children)
    builtin.execute_workflow({
        "run_id": str(root.id),
        "organization_id": str(organization.id),
        "definition_snapshot": {"durable_children": True, "workflow_steps": steps},
        "input": {"topic": "AI productivity"},
    }, _Sink())

    writer = root.child_runs.get(node_key="writer")
    layout = root.child_runs.get(node_key="layout")
    assert writer.input["message"] == "Topic: AI productivity\nMode: Full article"
    assert layout.input["message"] == "Topic: Rendered article\nMode: Full article"


@pytest.mark.django_db(transaction=True)
def test_workflow_child_output_is_mirrored_to_parent_stream():
    actor = get_user_model().objects.create_user(username="workflow-stream-owner")
    organization = actor.owned_organizations.get()
    root = create_run(
        organization=organization, owner=actor,
        executor_kind=Run.ExecutorKind.WORKFLOW, executor_key="workflow-dag",
        source_type="workflow", source_id="flow", definition_snapshot={},
        input_data={},
    )
    child = create_run(
        organization=organization, owner=actor, parent=root, node_key="writer",
        executor_kind=Run.ExecutorKind.AGENT, executor_key="agent-completion",
        source_type="workflow_step", source_id="step-1",
        definition_snapshot={
            "workflow_step_id": "step-1",
            "workflow_step_key": "writer",
            "workflow_step_name": "Writer",
        },
        input_data={},
    )

    event = mirror_child_output_event(
        child_run_id=child.id,
        organization_id=organization.id,
        event_type="output.delta",
        payload={"text": "live text"},
    )

    assert event.run_id == root.id
    assert event.type == "workflow.step.output.delta"
    assert event.payload["workflow_step_key"] == "writer"
    assert event.payload["text"] == "live text"


@pytest.mark.django_db(transaction=True)
def test_workflow_child_projects_prompt_and_result_to_conversation():
    actor = get_user_model().objects.create_user(username="workflow-conversation-owner")
    organization = actor.owned_organizations.get()
    conversation = Conversation.objects.create(
        user=actor,
        organization=organization,
        title="Flow · Writer",
    )
    child = create_run(
        organization=organization, owner=actor,
        executor_kind=Run.ExecutorKind.AGENT, executor_key="agent-completion",
        source_type="workflow_step", source_id="step-1",
        definition_snapshot={"conversation_id": str(conversation.id)},
        input_data={"message": "Write about AI"},
    )

    assert ConversationDetailSerializer(conversation).data["active_run"]["id"] == str(child.id)

    project_terminal_run(child.id, {"result": "Finished article"})

    messages = list(Message.objects.filter(conversation=conversation).order_by("created_at"))
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Write about AI"),
        ("assistant", "Finished article"),
    ]


@pytest.mark.parametrize(
    ("steps", "error"),
    [
        ([{"key": "same"}, {"key": "same"}], "duplicate step keys"),
        ([{"key": "one", "depends_on": ["missing"]}], "unknown dependencies"),
    ],
)
def test_durable_workflow_validates_graph_before_database_access(steps, error):
    with pytest.raises(RuntimeError, match=error):
        builtin.execute_workflow(
            {
                "definition_snapshot": {
                    "durable_children": True,
                    "workflow_steps": steps,
                },
                "input": {},
            },
            _Sink(),
        )


@pytest.mark.django_db
def test_agent_completion_projects_provider_question_to_durable_suspend(monkeypatch):
    actor = get_user_model().objects.create_user(username="interactive-agent")
    organization = actor.owned_organizations.get()

    class FakeEngine:
        def complete(self, messages, **options):
            assert messages[-1]["content"] == "hello"
            assert options["approval_decision"] == ""
            return LLMResponse(
                content="",
                usage=TokenUsage(),
                model="fake",
                input_request={
                    "input_kind": "answer",
                    "question": "Which format?",
                    "expires_in_seconds": 120,
                },
            )

    monkeypatch.setattr(
        "apps.agents.execution.build_agent_engine", lambda *_args, **_kwargs: FakeEngine()
    )
    sink = _SuspendSink()
    with pytest.raises(RuntimeError, match="suspended"):
        execute_agent_completion({
            "organization_id": str(organization.id),
            "definition_snapshot": {"agent_definition": {}},
            "input": {"message": "hello"},
        }, sink)

    assert sink.request == {
        "input_kind": "answer",
        "request_payload": {"question": "Which format?"},
        "checkpoint": {
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": "hello"},
            ],
            "input_request": {
                "input_kind": "answer",
                "question": "Which format?",
                "expires_in_seconds": 120,
            },
        },
        "expires_in_seconds": 120,
    }


def test_workflow_rejects_non_durable_execution():
    with pytest.raises(RuntimeError, match="requires durable child Runs"):
        builtin.execute_workflow(
            {"definition_snapshot": {"workflow_steps": []}, "input": {}},
            _Sink(),
        )

import sys
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from core.agent_engine.models import LLMResponse, TokenUsage
from modules.execution.runtime import builtin
from app_center.batch_transcribe import runtime as batch_transcribe
from apps.agents.execution import execute_agent_completion
from modules.execution.application.runs import create_run
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

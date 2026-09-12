import sys
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from core.agent_engine.models import LLMResponse, TokenUsage
from modules.execution.runtime import builtin


_dag_attempts = {}


def _fake_dag_adapter(run_payload, sink):
    step = run_payload["definition_snapshot"]
    key = step["key"]
    _dag_attempts[key] = _dag_attempts.get(key, 0) + 1
    if key == "retry" and _dag_attempts[key] == 1:
        raise RuntimeError("retry me")
    return {
        "key": key,
        "dependency_outputs": run_payload["input"].get("dependency_outputs", {}),
    }


class _Sink:
    def __init__(self):
        self.events = []

    @property
    def cancelled(self):
        return False

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


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

    result = builtin.execute_batch_transcribe(
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
        "core.llm.factory.build_agent_engine", lambda *_args, **_kwargs: FakeEngine()
    )
    sink = _SuspendSink()
    with pytest.raises(RuntimeError, match="suspended"):
        builtin.execute_agent_completion({
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
        },
        "expires_in_seconds": 120,
    }


def test_workflow_dag_dependencies_conditions_and_node_retry(settings):
    _dag_attempts.clear()
    settings.EXECUTION_WORKFLOW_MAX_PARALLELISM = 2
    settings.EXECUTION_CHILD_ADAPTERS = {
        "media": {
            "fake-dag": (
                "modules.execution.tests.test_builtin_runtime:_fake_dag_adapter"
            ),
        },
    }
    sink = _Sink()
    steps = [
        {
            "id": "1", "key": "root", "name": "Root", "depends_on": [],
            "condition": {}, "max_attempts": 1,
            "executor_kind": "media", "executor_key": "fake-dag", "content": {},
        },
        {
            "id": "2", "key": "retry", "name": "Retry", "depends_on": ["root"],
            "condition": {}, "max_attempts": 2,
            "executor_kind": "media", "executor_key": "fake-dag", "content": {},
        },
        {
            "id": "3", "key": "skipped", "name": "Skipped", "depends_on": ["root"],
            "condition": {
                "source": "input", "path": "enabled", "operator": "equals", "value": True,
            },
            "max_attempts": 1,
            "executor_kind": "media", "executor_key": "fake-dag", "content": {},
        },
    ]

    result = builtin.execute_workflow(
        {
            "definition_snapshot": {"workflow_steps": steps},
            "input": {"enabled": False},
        },
        sink,
    )

    assert result["status"] == "completed"
    assert _dag_attempts == {"root": 1, "retry": 2}
    by_key = {step["step_key"]: step for step in result["steps"]}
    assert by_key["retry"]["output"]["dependency_outputs"]["root"]["key"] == "root"
    assert by_key["skipped"]["status"] == "skipped"
    event_types = [event_type for event_type, _ in sink.events]
    assert event_types.count("workflow.step.failed") == 1
    assert "workflow.step.skipped" in event_types

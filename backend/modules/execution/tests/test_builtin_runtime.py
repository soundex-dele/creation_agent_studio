import sys
from types import SimpleNamespace

from modules.execution.runtime import builtin


class _Sink:
    def __init__(self):
        self.events = []

    @property
    def cancelled(self):
        return False

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


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

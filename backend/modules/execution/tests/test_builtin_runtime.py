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

    class FakeCore:
        def __init__(self, video_files, output_dir, model_size="base", language=None):
            seen["video_files"] = list(video_files)
            seen["output_dir"] = output_dir
            seen["model_size"] = model_size
            seen["language"] = language

        def run(self, sink):
            sink.emit("job.progress", {"current": 1, "total": 1})
            sink.emit("item.state", {"id": "a", "name": "a.mp4", "status": "done"})
            sink.emit("log", {"level": "info", "msg": "complete"})

    monkeypatch.setattr(builtin, "BatchTranscribeCore", FakeCore)
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

    assert len(seen["video_files"]) == 1
    assert seen["video_files"][0].endswith("a.mp4")
    assert seen["model_size"] == "tiny"
    assert seen["language"] == "zh"
    assert [event_type for event_type, _ in sink.events] == [
        "progress.updated",
        "tool.completed",
        "output.delta",
    ]
    assert result == {"status": "completed"}

import io
import json
import subprocess
from unittest.mock import Mock
import pytest
from app_center.web_fetch import runtime
from .test_fetch import Sink


class Input(io.BytesIO):
    # Keep the captured payload available to assertions after the parent closes it.
    def close(self):
        pass


def fake_process(monkeypatch, tmp_path, events):
    (tmp_path / "node_modules/playwright").mkdir(parents=True)
    (tmp_path / "node_modules/playwright/package.json").write_text("{}")
    monkeypatch.setattr(runtime, "ENGINE", tmp_path)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "node")
    process = Mock(pid=123, stdin=Input(), stdout=io.BytesIO(b"".join(json.dumps(event).encode() + b"\n" for event in events)))
    process.poll.return_value = 0
    process.returncode = 0
    process.wait.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    stop = Mock()
    monkeypatch.setattr(runtime, "stop_process", stop)
    return process, popen, stop


def test_engine_progress_and_json_protocol(monkeypatch, tmp_path):
    process, popen, stop = fake_process(monkeypatch, tmp_path, [
        {"type": "progress", "stage": "loading"}, {"type": "result", "document": {"markdown": "body"}}])
    sink = Sink()
    assert runtime.run_engine("https://example.com/", sink) == {"markdown": "body"}
    assert json.loads(process.stdin.getvalue())["url"] == "https://example.com/"
    assert sink.events == [("progress.updated", {"stage": "loading"})]
    assert not popen.call_args.kwargs.get("shell")
    stop.assert_called_once_with(process)


@pytest.mark.parametrize("code", ["UNSAFE_URL", "INTERACTION_REQUIRED", "EMPTY_CONTENT", "DOM_TOO_LARGE"])
def test_engine_failure_is_sanitized_and_cleaned_up(monkeypatch, tmp_path, code):
    process, _, stop = fake_process(monkeypatch, tmp_path, [{"type": "error", "code": code, "detail": "secret/path"}])
    with pytest.raises(RuntimeError, match=runtime.MESSAGES[code]):
        runtime.run_engine("https://example.com/", Sink())
    stop.assert_called_once_with(process)


def test_watchdog_and_cancel_always_stop_tree(monkeypatch, tmp_path):
    process, _, stop = fake_process(monkeypatch, tmp_path, [])
    monkeypatch.setattr(runtime, "TASK_TIMEOUT", -1)
    with pytest.raises(RuntimeError, match="超时"):
        runtime.run_engine("https://example.com/", Sink())
    stop.assert_called_once_with(process)
    stop.reset_mock()
    sink = Sink(); sink.cancelled = True
    process.stdout = io.BytesIO()
    assert runtime.run_engine("https://example.com/", sink) is None
    stop.assert_called_once_with(process)


def test_windows_termination_targets_entire_tree(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    process = Mock(pid=4321); process.poll.return_value = None
    run = Mock(); monkeypatch.setattr(runtime.subprocess, "run", run)
    runtime.stop_process(process)
    assert run.call_args.args[0] == ["taskkill", "/PID", "4321", "/T", "/F"]
    process.wait.assert_called_once_with(timeout=5)

import asyncio
import io
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory

from core.middleware import RequestLoggingMiddleware
from core.observability import (
    ContextFilter, ProcessingFormatter, current_log_context, log_context, log_operation,
)
from modules.execution.event_logging import log_run_event
from modules.execution.runtime import child


@pytest.fixture
def logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.setFormatter(ProcessingFormatter(
        "%(levelname)s %(name)s request_id=%(request_id)s run_id=%(run_id)s "
        "attempt_id=%(attempt_id)s %(message)s"))
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def test_service_logs_context_timing_and_preserves_result_without_payload(logs):
    @log_operation
    def process(run_id, content):
        logging.getLogger("apps.example").info("processing")
        return content

    private = {"token": "private-input"}
    with log_context(request_id="request-1"):
        assert process("run-1", private) is private
        assert current_log_context() == {"request_id": "request-1"}
    assert current_log_context() == {}
    output = logs.getvalue()
    assert "state=started" in output and "state=completed duration_ms=" in output
    assert "request_id=request-1 run_id=run-1" in output
    assert "private-input" not in output


def test_service_failure_has_frames_but_no_exception_payload(logs):
    error = ValueError("Bearer private-token https://example.test/?secret=hidden")

    @log_operation
    def fail():
        raise error

    with pytest.raises(ValueError) as caught:
        fail()
    assert caught.value is error
    output = logs.getvalue()
    assert "state=failed" in output and "in fail" in output and "ValueError" in output
    assert "private-token" not in output and "secret=hidden" not in output
    assert current_log_context() == {}


@pytest.mark.asyncio
async def test_concurrent_async_services_keep_context_separate(logs):
    @log_operation
    async def process(run_id):
        await asyncio.sleep(0)
        assert current_log_context()["run_id"] == run_id
        return run_id

    assert await asyncio.gather(process("one"), process("two")) == ["one", "two"]
    assert current_log_context() == {}


@pytest.mark.asyncio
async def test_cancelled_service_is_not_reported_as_failure(logs):
    @log_operation
    async def cancel(run_id):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await cancel("cancelled-run")
    assert "state=cancelled" in logs.getvalue()
    assert "ERROR" not in logs.getvalue()
    assert current_log_context() == {}


def test_formatter_does_not_reuse_unfiltered_exception_cache():
    try:
        raise ValueError("private-exception")
    except ValueError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    logging.Formatter().format(record)
    assert "private-exception" in record.exc_text
    assert "private-exception" not in ProcessingFormatter().format(record)


def test_image_returned_failure_is_visible_without_response_body(monkeypatch, logs):
    from core.agent_engine import image_provider
    from core.agent_engine.models import ImageConfig

    monkeypatch.setattr(image_provider.requests, "post", lambda *a, **kw:
                        SimpleNamespace(ok=False, status_code=503, text="private-provider-body"))
    result = image_provider.ImageProvider(ImageConfig()).generate("private-prompt")
    assert result.success is False
    assert "state=rejected http_status=503" in logs.getvalue()
    assert "private-provider-body" not in logs.getvalue()
    assert "private-prompt" not in logs.getvalue()


@pytest.mark.django_db
def test_http_and_stream_processing_keep_request_context_and_reset(logs):
    request = RequestFactory().get("/private-path?token=hidden")
    request.request_id = "req-stream"

    def content():
        assert current_log_context()["request_id"] == "req-stream"
        yield b"first"
        assert current_log_context()["request_id"] == "req-stream"
        yield b"second"

    middleware = RequestLoggingMiddleware(lambda req: StreamingHttpResponse(content()))
    response = middleware(request)
    assert current_log_context() == {}
    chunks = iter(response.streaming_content)
    assert next(chunks) == b"first"
    assert current_log_context() == {}
    assert list(chunks) == [b"second"]
    response.close()
    output = logs.getvalue()
    assert "state=stream_ready" in output and "request.stream state=closed" in output
    assert "private-path" not in output and "hidden" not in output


@pytest.mark.asyncio
async def test_async_stream_failure_keeps_context_and_logs_traceback(logs):
    request = RequestFactory().get("/")
    request.request_id = "async-stream"

    async def content():
        assert current_log_context()["request_id"] == "async-stream"
        yield b"first"
        raise RuntimeError("private-body")

    response = RequestLoggingMiddleware(lambda req: StreamingHttpResponse(content()))(request)
    stream = response.streaming_content
    assert await anext(stream) == b"first"
    assert current_log_context() == {}
    with pytest.raises(RuntimeError):
        await anext(stream)
    assert current_log_context() == {}
    assert "request.stream state=failed" in logs.getvalue()
    assert "private-body" not in logs.getvalue()


def test_all_view_modules_are_named_in_processing_logs(logs):
    request = RequestFactory().post("/")
    request.request_id = "http-1"

    def view(request):
        return HttpResponse()

    def dispatch(request):
        middleware.process_view(request, view, (), {})
        return view(request)

    middleware = RequestLoggingMiddleware(dispatch)
    assert middleware(request).status_code == 200
    assert "view=test_all_view_modules_are_named_in_processing_logs.<locals>.view" in logs.getvalue()
    assert current_log_context() == {}


def test_child_failure_keeps_terminal_protocol_and_context(monkeypatch, logs):
    monkeypatch.setattr(child, "_initialize_django", lambda: None)

    def fail(payload, sink):
        assert current_log_context()["run_id"] == "run-1"
        raise ValueError("private failure")

    monkeypatch.setattr(child, "_load_entrypoint", lambda _: fail)
    messages, cancel = Mock(), Mock()
    cancel.is_set.return_value = False
    child.execute_child({"run_id": "run-1", "attempt_id": "attempt-1"}, messages, cancel, "example:run")
    assert messages.put.call_count == 1
    assert messages.put.call_args.args[0]["outcome"] == "failed"
    assert "run_id=run-1 attempt_id=attempt-1" in logs.getvalue()
    assert "in fail" in logs.getvalue()
    assert "private failure" not in logs.getvalue()
    assert current_log_context() == {}


def test_suspend_is_not_logged_as_failure(monkeypatch, logs):
    monkeypatch.setattr(child, "_initialize_django", lambda: None)

    @log_operation
    def suspend(run_payload, sink):
        sink.wait_for_children(child_run_ids=["child"], checkpoint={})

    monkeypatch.setattr(child, "_load_entrypoint", lambda _: suspend)
    messages = Mock()
    child.execute_child({"run_id": "run-1"}, messages, Mock(), "example:run")
    assert "state=suspended" in logs.getvalue()
    assert "ERROR" not in logs.getvalue()
    assert messages.put.call_count == 1
    assert messages.put.call_args.args[0]["kind"] == "wait_for_children"


def test_progress_logs_stage_changes_and_throttles_counts(monkeypatch, logs):
    monkeypatch.setattr(child.time, "monotonic", lambda: 10)
    sink = child.ChildEventSink(Mock(), Mock())
    sink.emit("progress.updated", {"stage": "download", "current": 1, "total": 9, "message": "private"})
    sink.emit("progress.updated", {"stage": "download", "current": 2, "total": 9})
    sink.emit("progress.updated", {"stage": "transcribe", "current": 3, "total": 9})
    sink.emit("output.delta", {"text": "private"})
    output = logs.getvalue()
    assert "stage=download current=1 total=9" in output
    assert "current=2" not in output
    assert "stage=transcribe" in output
    assert "private" not in output
    assert sink._queue.put.call_count == 4


@pytest.mark.django_db
def test_lifecycle_logs_only_committed_events(logs):
    from django.db import transaction

    event = SimpleNamespace(type="run.retry_scheduled", run_id="run-1", attempt_id="attempt-1",
                            organization_id="org-1", sequence=5,
                            payload={"error_code": "worker_lost", "error_message": "private"})
    callbacks = []
    from django.test import TestCase
    with TestCase.captureOnCommitCallbacks(execute=True) as callbacks:
        with log_context(request_id="submit-1"):
            log_run_event(None, event, True)
        assert "state=committed" not in logs.getvalue()
        with pytest.raises(ValueError), transaction.atomic():
            log_run_event(None, event, True)
            raise ValueError("rollback")
    assert len(callbacks) == 1
    assert logs.getvalue().count("state=committed") == 1
    assert "request_id=submit-1" in logs.getvalue()
    assert "private" not in logs.getvalue()


@pytest.mark.parametrize("profile", ["development", "production", "desktop"])
def test_profiles_emit_processing_logs_to_stdout(profile):
    script = (
        "import importlib, logging, logging.config; "
        f"s=importlib.import_module('backend.settings.{profile}'); "
        "logging.config.dictConfig(s.LOGGING); "
        "[logging.getLogger(n).info('processing-visible') for n in "
        "['apps.example','core.example','modules.example','app_center.example']]"
    )
    env = {**os.environ, "SECRET_KEY": "x" * 60, "REDIS_ENABLED": "False",
           "REMOTE_RELAY_ENABLED": "False", "LOG_LEVEL": "INFO"}
    result = subprocess.run([sys.executable, "-c", script], env=env,
                            cwd=Path(__file__).resolve().parents[2],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("processing-visible") == 4
    assert "processing-visible" not in result.stderr

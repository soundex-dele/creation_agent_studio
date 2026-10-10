import importlib
import logging
import time
import queue
from uuid import uuid4
from pathlib import Path

from core.observability import log_context, operation, _identifier


logger = logging.getLogger(__name__)


class _SuspendExecution(Exception):
    log_outcome = "suspended"


def _initialize_django():
    """Initialize Django inside a fresh multiprocessing ``spawn`` child."""

    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _load_entrypoint(dotted_path):
    try:
        separator = ":" if ":" in dotted_path else "."
        module_name, attribute_name = dotted_path.rsplit(separator, 1)
        entrypoint = getattr(importlib.import_module(module_name), attribute_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise RuntimeError(f"Cannot load execution adapter {dotted_path!r}") from exc
    if not callable(entrypoint):
        raise RuntimeError(f"Execution adapter {dotted_path!r} is not callable")
    return entrypoint


class ChildEventSink:
    """Small database-free protocol exposed to an execution adapter."""

    def __init__(self, message_queue, cancel_event, controls=None):
        self._queue = message_queue
        self._cancel_event = cancel_event
        self._controls = controls
        self._deferred_commands = []

    def poll_commands(self):
        if self._controls is None:
            return []
        commands, self._deferred_commands = self._deferred_commands, []
        while True:
            try:
                commands.append(self._controls.get_nowait())
            except queue.Empty:
                return commands

    def wait_for_input(self, request, *, is_pending=lambda: True):
        if self._controls is None:
            raise RuntimeError("Live provider input requires a bidirectional worker")
        request_id = str(uuid4())
        logger.info("execution.input state=waiting input_request_id=%s", request_id)
        self._queue.put({"kind": "live_input", "input_request_id": request_id,
                         "input_kind": request.get("input_kind", "answer"),
                         "request_payload": request})
        try:
            while not self.cancelled and is_pending():
                try:
                    command = self._controls.get(timeout=0.1)
                except queue.Empty:
                    continue
                if command.get("input_request_id") == request_id:
                    return command
                if command.get("type") == "steer":
                    self._deferred_commands.append(command)
            return None
        finally:
            logger.info("execution.input state=resolved input_request_id=%s", request_id)
            self._queue.put({"kind": "live_input_resolved", "input_request_id": request_id})

    @property
    def cancelled(self):
        return self._cancel_event.is_set()

    def emit(self, event_type, payload):
        # Payloads contain prompts, tool arguments and generated text. Log only
        # the event type here; durable events retain the detailed UI content.
        if str(event_type) not in {"output.delta", "output.snapshot", "agent.item"}:
            level = logging.ERROR if str(event_type).endswith(".failed") else logging.INFO
            stage = str((payload or {}).get("stage", ""))
            if event_type == "progress.updated" or str(event_type).endswith(".progress"):
                # Keep long media jobs observable without logging every audio frame.
                now = time.monotonic()
                if (stage == getattr(self, "_last_progress_stage", None)
                        and now - getattr(self, "_last_progress_log", float("-inf")) < 5):
                    level = logging.DEBUG
                else:
                    self._last_progress_log = now
                    self._last_progress_stage = stage
            # Stages are bounded labels; exclude free-text messages/tool arguments.
            counts = " ".join(f"{key}={payload[key]}" for key in
                              ("current", "total", "done", "seconds")
                              if isinstance((payload or {}).get(key), (int, float)))
            logger.log(level, "execution.event type=%s stage=%s %s",
                       event_type, _identifier(stage), counts)
        self._queue.put(
            {
                "kind": "event",
                "type": str(event_type),
                "payload": dict(payload or {}),
            }
        )

    def create_artifact(
        self, *, kind, filename, content, mime_type="application/octet-stream", metadata=None
    ):
        """Submit artifact content; only the coordinator chooses its object key."""

        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, bytes):
            raise TypeError("Artifact content must be bytes or text")
        logger.info("execution.artifact state=submitted bytes=%s", len(content))
        self._queue.put({
            "kind": "artifact",
            "artifact_kind": str(kind),
            "filename": Path(str(filename)).name,
            "content": content,
            "mime_type": str(mime_type),
            "metadata": dict(metadata or {}),
        })

    def request_input(
        self,
        *,
        input_kind,
        request_payload,
        checkpoint,
        expires_in_seconds=86400,
    ):
        """Suspend this attempt; the coordinator durably persists the checkpoint."""
        self._queue.put({
            "kind": "suspend",
            "input_kind": str(input_kind),
            "request_payload": dict(request_payload or {}),
            "checkpoint": dict(checkpoint or {}),
            "expires_in_seconds": int(expires_in_seconds),
        })
        raise _SuspendExecution()

    def wait_for_children(self, *, child_run_ids, checkpoint):
        """Suspend a workflow attempt without presenting a user-input request."""

        values = [str(value) for value in child_run_ids]
        if not values:
            raise ValueError("At least one child Run is required")
        self._queue.put({
            "kind": "wait_for_children",
            "child_run_ids": values,
            "checkpoint": dict(checkpoint or {}),
        })
        raise _SuspendExecution()


def execute_child(run_payload, message_queue, cancel_event, adapter_entrypoint, controls=None):
    """Spawn-safe process entry point; adapters receive data and an IPC sink."""

    with log_context(**{key: run_payload.get(key) for key in
                        ("run_id", "attempt_id", "organization_id", "worker_id")}):
        _execute_child(run_payload, message_queue, cancel_event, adapter_entrypoint, controls)


def _execute_child(run_payload, message_queue, cancel_event, adapter_entrypoint, controls):
    started = time.perf_counter()
    try:
        _initialize_django()
        logger.info(
            "chat_latency stage=child_django_ready run_id=%s init_ms=%.1f",
            run_payload.get("run_id", "unknown"), (time.perf_counter() - started) * 1000,
        )
        with operation("execution.adapter", logger=logger):
            logger.info("execution.adapter entrypoint=%s state=loading", adapter_entrypoint)
            adapter = _load_entrypoint(adapter_entrypoint)
            output = adapter(run_payload, ChildEventSink(message_queue, cancel_event, controls))
        outcome = "cancelled" if cancel_event.is_set() else "succeeded"
        logger.info("execution.child state=%s duration_ms=%.1f", outcome,
                    (time.perf_counter() - started) * 1000)
        message_queue.put(
            {"kind": "terminal", "outcome": outcome, "output": output or {}}
        )
    except _SuspendExecution:
        return
    except BaseException as exc:
        if isinstance(exc, InterruptedError) and cancel_event.is_set():
            logger.info("execution.child state=cancelled duration_ms=%.1f",
                        (time.perf_counter() - started) * 1000)
            message_queue.put({"kind": "terminal", "outcome": "cancelled", "output": {}})
            return
        logger.exception("execution.child state=failed error_type=%s", type(exc).__name__)
        message_queue.put(
            {
                "kind": "terminal",
                "outcome": "failed",
                "error_code": "execution_adapter_failed",
                "error_message": str(exc)[:2000],
            }
        )

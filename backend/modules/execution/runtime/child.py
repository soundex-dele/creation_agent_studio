import importlib
import logging
import time
from pathlib import Path


class _SuspendExecution(Exception):
    pass


def _initialize_django():
    """Initialize Django inside a fresh multiprocessing ``spawn`` child."""

    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _load_entrypoint(dotted_path):
    try:
        module_name, attribute_name = dotted_path.split(":", 1)
        entrypoint = getattr(importlib.import_module(module_name), attribute_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise RuntimeError(f"Cannot load execution adapter {dotted_path!r}") from exc
    if not callable(entrypoint):
        raise RuntimeError(f"Execution adapter {dotted_path!r} is not callable")
    return entrypoint


class ChildEventSink:
    """Small database-free protocol exposed to an execution adapter."""

    def __init__(self, message_queue, cancel_event):
        self._queue = message_queue
        self._cancel_event = cancel_event

    @property
    def cancelled(self):
        return self._cancel_event.is_set()

    def emit(self, event_type, payload):
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


def execute_child(run_payload, message_queue, cancel_event, adapter_entrypoint):
    """Spawn-safe process entry point; adapters receive data and an IPC sink."""

    started = time.perf_counter()
    try:
        _initialize_django()
        logging.getLogger(__name__).info(
            "chat_latency stage=child_django_ready run_id=%s init_ms=%.1f",
            run_payload.get("run_id", "unknown"), (time.perf_counter() - started) * 1000,
        )
        adapter = _load_entrypoint(adapter_entrypoint)
        output = adapter(run_payload, ChildEventSink(message_queue, cancel_event))
        outcome = "cancelled" if cancel_event.is_set() else "succeeded"
        message_queue.put(
            {"kind": "terminal", "outcome": outcome, "output": output or {}}
        )
    except _SuspendExecution:
        return
    except BaseException as exc:
        message_queue.put(
            {
                "kind": "terminal",
                "outcome": "failed",
                "error_code": "execution_adapter_failed",
                "error_message": str(exc)[:2000],
            }
        )

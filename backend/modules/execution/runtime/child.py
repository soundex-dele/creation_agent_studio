import importlib


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


def execute_child(run_payload, message_queue, cancel_event, adapter_entrypoint):
    """Spawn-safe process entry point; adapters receive data and an IPC sink."""

    try:
        _initialize_django()
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

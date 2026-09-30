"""Small, payload-free processing logs shared by HTTP and worker processes."""

import asyncio
import inspect
import logging
import re
import time
import traceback
from copy import copy
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from uuid import UUID


_context = ContextVar("processing_log_context", default={})
CONTEXT_FIELDS = ("request_id", "run_id", "attempt_id", "organization_id", "worker_id")


def current_log_context():
    return dict(_context.get())


def _identifier(value):
    if not isinstance(value, (str, int, UUID)):
        return "-"
    return re.sub(r"[^\w.:@/-]", "_", str(value))[:128] or "-"


@contextmanager
def log_context(**values):
    """Nest and restore context; never keep one request/run's IDs for the next."""
    token = _context.set({
        **_context.get(),
        **{key: _identifier(value) for key, value in values.items()
           if key in CONTEXT_FIELDS and value is not None},
    })
    try:
        yield
    finally:
        _context.reset(token)


class ContextFilter(logging.Filter):
    def filter(self, record):
        for key in CONTEXT_FIELDS:
            setattr(record, key, _identifier(getattr(record, key, _context.get().get(key, "-"))))
        return True


class ProcessingFormatter(logging.Formatter):
    def format(self, record):
        # Another handler may have cached an unfiltered traceback on this record.
        record = copy(record)
        record.exc_text = None
        return super().format(record)

    def formatException(self, exc_info):
        # Provider/HTTP exception messages can embed authorization, signed URLs,
        # transcripts or model output. Retain every stack frame and error type,
        # but never include exception values or frame locals.
        seen = set()

        def render(exc, tb):
            if id(exc) in seen:
                return ""
            seen.add(id(exc))
            cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
            prefix = render(cause, cause.__traceback__) + "\nCaused by:\n" if cause else ""
            frames = "".join(
                f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
                for frame in traceback.extract_tb(tb)
            )
            return prefix + "Traceback (most recent call last):\n" + frames + type(exc).__name__

        return render(exc_info[1], exc_info[2])


@contextmanager
def operation(name, *, logger=None, level=logging.INFO, **context):
    """Log a processing boundary without serializing arguments or results."""
    logger = logger or logging.getLogger(__name__)
    started = time.perf_counter()
    with log_context(**context):
        logger.log(level, "operation=%s state=started", name)
        try:
            yield
        except BaseException as exc:
            outcome = getattr(type(exc), "log_outcome", None)
            if isinstance(exc, (InterruptedError, asyncio.CancelledError, GeneratorExit, KeyboardInterrupt)):
                outcome = "cancelled"
            if outcome in {"cancelled", "suspended"}:
                logger.info("operation=%s state=%s duration_ms=%.1f", name, outcome,
                            (time.perf_counter() - started) * 1000)
            else:
                # Include the traceback: worker IPC otherwise only retains str(exc).
                logger.error("operation=%s state=failed duration_ms=%.1f error_type=%s",
                             name, (time.perf_counter() - started) * 1000,
                             type(exc).__name__, exc_info=True)
            raise
        else:
            logger.log(level, "operation=%s state=completed duration_ms=%.1f",
                       name, (time.perf_counter() - started) * 1000)


def log_operation(function=None, *, level=logging.INFO):
    """Explicit service instrumentation. Only known correlation IDs are read."""
    if function is None:
        return lambda wrapped: log_operation(wrapped, level=level)
    if inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function):
        raise TypeError("Instrument generator processing inside iteration, not at creation")
    signature = inspect.signature(function)
    logger = logging.getLogger(function.__module__)

    def scope(args, kwargs):
        arguments = signature.bind_partial(*args, **kwargs).arguments
        payload = arguments.get("run_payload")
        if payload is None and "sink" in arguments:
            payload = arguments.get("payload")
        context = {key: arguments[key] for key in CONTEXT_FIELDS if key in arguments}
        if isinstance(payload, dict):
            context.update({key: payload[key] for key in CONTEXT_FIELDS if key in payload})
        return operation(function.__qualname__, logger=logger, level=level, **context)

    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def async_wrapped(*args, **kwargs):
            with scope(args, kwargs):
                return await function(*args, **kwargs)
        return async_wrapped

    @wraps(function)
    def wrapped(*args, **kwargs):
        with scope(args, kwargs):
            return function(*args, **kwargs)
    return wrapped

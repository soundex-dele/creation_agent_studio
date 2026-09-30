"""
Custom middleware for Agent Studio.
"""
import time
import logging
from uuid import uuid4

from core.observability import log_context

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """Bind processing logs to a request, including lazy streaming execution."""

    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        context = {"request_id": getattr(request, "request_id", None) or uuid4().hex}
        with log_context(**context):
            response = self.get_response(request)
            match = getattr(request, "resolver_match", None)
            # Use the route template, not paths/query strings that may contain secrets.
            route = getattr(match, "route", None) or "unmatched"
            level = logging.ERROR if response.status_code >= 500 else (
                logging.WARNING if response.status_code >= 400 else logging.INFO)
            logger.log(level, "request state=%s method=%s route=%s status=%s duration_ms=%.1f",
                       "stream_ready" if response.streaming else "completed",
                       request.method, route, response.status_code,
                       (time.perf_counter() - started) * 1000)
        if response.streaming:
            content = response.streaming_content
            if response.is_async:
                async def async_stream():
                    try:
                        while True:
                            with log_context(**context):
                                try:
                                    chunk = await anext(content)
                                except StopAsyncIteration:
                                    break
                            yield chunk
                    except Exception:
                        with log_context(**context):
                            logger.exception("request.stream state=failed")
                        raise
                    finally:
                        with log_context(**context):
                            logger.info("request.stream state=closed duration_ms=%.1f",
                                        (time.perf_counter() - started) * 1000)
                response.streaming_content = async_stream()
            else:
                def stream():
                    try:
                        while True:
                            with log_context(**context):
                                try:
                                    chunk = next(content)
                                except StopIteration:
                                    break
                            yield chunk
                    except Exception:
                        with log_context(**context):
                            logger.exception("request.stream state=failed")
                        raise
                    finally:
                        with log_context(**context):
                            logger.info("request.stream state=closed duration_ms=%.1f",
                                        (time.perf_counter() - started) * 1000)
                response.streaming_content = stream()
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        view_class = getattr(view_func, "cls", None) or getattr(view_func, "view_class", None)
        target = view_class or view_func
        logging.getLogger(getattr(target, "__module__", type(target).__module__)).info(
            "view=%s state=started method=%s",
            getattr(target, "__qualname__", type(target).__qualname__), request.method)

    def process_exception(self, request, exception):
        logger.error("request state=failed error_type=%s", type(exception).__name__,
                     exc_info=(type(exception), exception, exception.__traceback__))

"""
Custom middleware for Agent Studio.
"""
import time
import logging
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log all incoming requests with timing information.
    """

    def process_request(self, request):
        """Store request start time."""
        request.start_time = time.time()

    def process_response(self, request, response):
        """Log request with timing."""
        if hasattr(request, 'start_time'):
            duration = time.time() - request.start_time
            logger.info(
                f'{request.method} {request.path} - '
                f'Status: {response.status_code} - '
                f'Duration: {duration:.3f}s'
            )
        return response

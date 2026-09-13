import ipaddress
import logging
import re
import time
import uuid

from django.db import transaction
from django.utils.deprecation import MiddlewareMixin

from .models import AuditLog


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,64}$')


def _bounded_audit_value(field_name, value):
    max_length = AuditLog._meta.get_field(field_name).max_length
    return str(value or '')[:max_length]


def _valid_ip_address(value):
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


class RequestContextMiddleware(MiddlewareMixin):
    """Attach correlation id and persist mutation audit records."""

    def process_request(self, request):
        candidate = request.headers.get('X-Request-ID', '')
        request.request_id = (
            candidate if REQUEST_ID_PATTERN.fullmatch(candidate)
            else uuid.uuid4().hex
        )
        request._audit_started_at = time.monotonic()

    def process_response(self, request, response):
        response['X-Request-ID'] = getattr(request, 'request_id', '')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            user = getattr(request, 'user', None)
            if user and user.is_authenticated:
                organization = getattr(request, 'organization', None)
                if organization is None:
                    membership = user.organization_memberships.filter(
                        is_active=True).select_related('organization').first()
                    organization = membership.organization if membership else None
                forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
                ip_address = forwarded.split(',')[0].strip() if forwarded else \
                    request.META.get('REMOTE_ADDR')
                try:
                    # Isolate audit failures behind a savepoint. Catching a
                    # DatabaseError directly inside the request transaction
                    # leaves it marked for rollback even if the exception is
                    # suppressed, which can otherwise return 2xx for a write
                    # that PostgreSQL silently rolls back.
                    with transaction.atomic():
                        AuditLog.objects.create(
                            organization=organization,
                            actor=user,
                            action=_bounded_audit_value(
                                'action',
                                f'{request.method.lower()}:'
                                f'{request.resolver_match.route if request.resolver_match else request.path}',
                            ),
                            resource_type=_bounded_audit_value(
                                'resource_type',
                                request.resolver_match.app_name
                                if request.resolver_match else '',
                            ),
                            resource_id=_bounded_audit_value(
                                'resource_id',
                                (request.resolver_match.kwargs or {}).get('pk', '')
                                if request.resolver_match else '',
                            ),
                            request_id=_bounded_audit_value(
                                'request_id', getattr(request, 'request_id', '')),
                            ip_address=_valid_ip_address(ip_address),
                            user_agent=request.headers.get('User-Agent', '')[:1000],
                            metadata={
                                'path': request.path,
                                'status_code': response.status_code,
                                'duration_ms': int(
                                    (time.monotonic() - request._audit_started_at) * 1000),
                            },
                        )
                except Exception:
                    # Audit failure must not turn a successful business
                    # request into 500 or poison its surrounding transaction.
                    logger.exception(
                        'Audit log write failed for request_id=%s',
                        getattr(request, 'request_id', ''),
                    )
        return response

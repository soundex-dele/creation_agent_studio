"""Authentication backends for scoped API keys."""
from django.conf import settings
from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication

from .licensing import LicenseError, load_installed_license, validate_license
from .models import UserAPIKey


def _require_active_license() -> None:
    if not settings.LICENSE_AUTH_ENABLED:
        return
    token = load_installed_license()
    if not token:
        raise exceptions.AuthenticationFailed('本机未安装许可证')
    try:
        validate_license(token)
    except LicenseError as exc:
        raise exceptions.AuthenticationFailed(str(exc)) from exc


class LicenseAwareJWTAuthentication(JWTAuthentication):
    """Reject desktop JWTs as soon as the installed license becomes invalid."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return result
        _require_active_license()
        return result


class ScopedAPIKeyAuthentication(authentication.BaseAuthentication):
    keyword = 'ApiKey'

    def authenticate(self, request):
        raw_key = request.headers.get('X-API-Key', '').strip()
        if not raw_key:
            authorization = authentication.get_authorization_header(request).decode('utf-8')
            if authorization.startswith(f'{self.keyword} '):
                raw_key = authorization[len(self.keyword) + 1:].strip()
        if not raw_key:
            return None

        _require_active_license()

        prefix = raw_key[:12]
        candidates = UserAPIKey.objects.select_related('user').filter(
            prefix=prefix, revoked_at__isnull=True, user__is_active=True
        )
        now = timezone.now()
        for api_key in candidates:
            if api_key.expires_at and api_key.expires_at <= now:
                continue
            if api_key.matches(raw_key):
                required_scope = 'read' if request.method in SAFE_METHODS else 'write'
                scopes = set(api_key.scopes or [])
                if scopes and not scopes.intersection(
                        {required_scope, 'admin', '*'}):
                    raise exceptions.PermissionDenied(
                        f'API key does not include the {required_scope!r} scope.')
                UserAPIKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
                request.api_key = api_key
                return api_key.user, api_key
        raise exceptions.AuthenticationFailed('Invalid or expired API key.')

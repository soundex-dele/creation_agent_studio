import base64
import hashlib
import json
import secrets
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone
from rest_framework import authentication, exceptions

from apps.enterprise.models import Membership
from apps.users.authentication import _require_active_license
from .models import LocalRemoteConfig, RemoteDevice
from .protocol import validate_request


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encrypt_credentials(value):
    key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ":remote-access").encode()).digest())
    return Fernet(key).encrypt(json.dumps(value).encode()).decode()


def decrypt_credentials(value):
    if not value:
        return {}
    key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ":remote-access").encode()).digest())
    return json.loads(Fernet(key).decrypt(value.encode()))


def validate_server_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise exceptions.ValidationError({"server_url": "请输入服务器 HTTP/HTTPS 根地址。"})
    return value.rstrip("/")


def authorized_user(config):
    user = config.local_user
    if not user or not user.is_active or not config.organization or not config.organization.is_active:
        raise exceptions.PermissionDenied("本地授权用户或组织不可用。")
    if not Membership.objects.filter(user=user, organization=config.organization, is_active=True).exists():
        raise exceptions.PermissionDenied("本地用户不再属于授权组织。")
    if settings.SINGLE_TENANT_MODE:
        from apps.enterprise.tenancy import get_single_tenant_organization
        if get_single_tenant_organization() != config.organization:
            raise exceptions.PermissionDenied("授权组织与本机组织不一致。")
    return user


def authenticate_device(device_id, token, *, paired=False):
    device = RemoteDevice.objects.select_related("owner").filter(pk=device_id, revoked_at__isnull=True).first()
    if (not device or not token or not secrets.compare_digest(device.token_hash, digest(token))
            or (not device.confirmed and device.pairing_expires_at <= timezone.now())
            or (paired and (not device.confirmed or not device.owner or not device.owner.is_active))):
        raise exceptions.AuthenticationFailed("Invalid device credential")
    return device


class LocalConnectorAuthentication(authentication.BaseAuthentication):
    """A separate loopback-only credential, never sent to the relay."""
    def authenticate_header(self, request):
        return 'Bearer realm="api"'

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("RemoteLocal "):
            return None
        if not settings.REMOTE_ACCESS_HOST_ENABLED or request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
            raise exceptions.AuthenticationFailed("Local connector authentication is unavailable")
        config = LocalRemoteConfig.objects.select_related("local_user", "organization").filter(pk=1).first()
        if not config or not config.enabled or not config.bound_account:
            raise exceptions.AuthenticationFailed("Remote access is disabled")
        expected = decrypt_credentials(config.credentials).get("local_token", "")
        if not expected or not secrets.compare_digest(header[12:], expected):
            raise exceptions.AuthenticationFailed("Invalid local credential")
        _require_active_license()
        user = authorized_user(config)
        try:
            validate_request(request.method, request.get_full_path(),
                             request.data if request.method == "POST" else None, config.organization_id)
        except ValueError as exc:
            raise exceptions.PermissionDenied(str(exc)) from exc
        # Ignore the relay's organization selection. Always bind the local grant.
        request.META["HTTP_X_ORGANIZATION_ID"] = str(config.organization_id)
        # Reading Authorization above materializes Django's cached HttpHeaders.
        # Rebuild it so downstream organization resolution sees the forced grant.
        request._request.__dict__.pop("headers", None)
        request.remote_connector = True
        request.remote_organization_id = config.organization_id
        return user, None

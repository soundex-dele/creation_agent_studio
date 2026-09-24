import secrets
from datetime import timedelta

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import exceptions, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.enterprise.models import Membership, Organization
from .models import LocalRemoteConfig, RemoteDevice
from .security import (
    authenticate_device, authorized_user, decrypt_credentials, digest,
    encrypt_credentials, validate_server_url,
)


def require_host(request):
    if not settings.REMOTE_ACCESS_HOST_ENABLED:
        raise exceptions.NotFound()
    if not (request.user.is_superuser or request.user.role == "admin"):
        raise exceptions.PermissionDenied("只有本地管理员可以配置远程访问。")


def require_relay():
    if not settings.REMOTE_RELAY_ENABLED:
        raise exceptions.NotFound()


def local_config():
    return LocalRemoteConfig.objects.get_or_create(pk=1)[0]


class DeviceCredentialExpired(exceptions.ValidationError):
    default_detail = "配对已过期或绑定已撤销，请重新配对。"


class LocalConfigChanged(exceptions.APIException):
    status_code = 409
    default_detail = "远程访问设置已更改，请刷新后重试。"


def save_local_action(config, original, *, force_fields=()):
    # A single conditional UPDATE is atomic on SQLite too. Do not hold a read
    # transaction across relay HTTP calls: connector heartbeats would invalidate
    # its WAL snapshot and SQLite cannot upgrade that snapshot to a writer.
    changes = {
        field: getattr(config, field)
        for field, value in original.items()
        if field in force_fields or getattr(config, field) != value
    }
    changes["revision"] = config.revision + 1
    if not LocalRemoteConfig.objects.filter(pk=config.pk, revision=config.revision).update(**changes):
        raise LocalConfigChanged()
    config.refresh_from_db()


def server_call(config, action, data=None, *, method="POST"):
    credentials = decrypt_credentials(config.credentials)
    try:
        response = httpx.request(
            method, f"{config.server_url}/api/v1/remote/{action}",
            json=data, headers={"Authorization": "Device " + credentials.get("device_token", "")},
            timeout=10, follow_redirects=False, trust_env=False,
        )
        if response.status_code not in {200, 201, 204}:
            if response.status_code in {401, 404, 410}:
                raise DeviceCredentialExpired()
            raise exceptions.ValidationError("服务器未接受操作，请检查服务器地址和连接。")
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise exceptions.ValidationError("无法连接服务器，请检查地址和网络后重试。") from exc


def config_data(config):
    alive = config.connector_seen_at and (timezone.now() - config.connector_seen_at).total_seconds() < 5
    return {
        "host_enabled": True, "manageable": True,
        "server_url": config.server_url, "computer_name": config.computer_name,
        "enabled": config.enabled, "local_user_id": config.local_user_id,
        "terminal_enabled": config.terminal_enabled,
        "file_transfer_enabled": config.file_transfer_enabled,
        "organization_id": str(config.organization_id) if config.organization_id else None,
        "device_id": str(config.device_id) if config.device_id else None,
        "bound_account": config.bound_account,
        "pairing_code": config.pairing_code if config.pairing_expires_at and config.pairing_expires_at > timezone.now() else "",
        "pairing_expires_at": config.pairing_expires_at,
        "status": (config.status if alive else "offline") if config.enabled else "disabled",
    }


class ConfigInput(serializers.Serializer):
    server_url = serializers.CharField(max_length=200)
    computer_name = serializers.CharField(max_length=100)
    enabled = serializers.BooleanField()
    terminal_enabled = serializers.BooleanField(required=False)
    file_transfer_enabled = serializers.BooleanField(required=False)
    local_user_id = serializers.IntegerField()
    organization_id = serializers.UUIDField()


class LocalConfigView(APIView):
    def get(self, request):
        if not settings.REMOTE_ACCESS_HOST_ENABLED:
            return Response({"host_enabled": False, "manageable": False})
        if not (request.user.is_superuser or request.user.role == "admin"):
            return Response({"host_enabled": True, "manageable": False})
        config = local_config()
        result = config_data(config)
        result["users"] = list(get_user_model().objects.filter(is_active=True).values("id", "username"))
        result["organizations"] = list(Organization.objects.filter(is_active=True).values("id", "name"))
        result["memberships"] = list(Membership.objects.filter(is_active=True).values("user_id", "organization_id"))
        return Response(result)

    @transaction.atomic
    def put(self, request):
        require_host(request)
        local_config()
        config = LocalRemoteConfig.objects.select_for_update().get(pk=1)
        serializer = ConfigInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        values["server_url"] = validate_server_url(values["server_url"])
        if config.device_id and any([
            config.server_url != values["server_url"],
            config.local_user_id != values["local_user_id"],
            config.organization_id != values["organization_id"],
        ]):
            raise exceptions.ValidationError("请先解绑，再更换服务器、授权用户或组织。")
        for key, value in values.items():
            setattr(config, key, value)
        try:
            authorized_user(config)
        except (get_user_model().DoesNotExist, Organization.DoesNotExist) as exc:
            raise exceptions.ValidationError("请选择有效的本地用户和组织。") from exc
        config.revision += 1
        config.status = "connecting" if config.enabled else "disabled"
        config.save()
        return Response(config_data(config))


class LocalActionView(APIView):
    def post(self, request, action):
        require_host(request)
        config = local_config()
        original = {
            field: getattr(config, field)
            for field in (
                "enabled", "device_id", "credentials", "bound_account",
                "pairing_code", "pairing_expires_at", "status",
            )
        }
        if action == "pair":
            if not config.server_url:
                raise exceptions.ValidationError("请先保存服务器和授权设置。")
            authorized_user(config)
            if config.bound_account:
                raise exceptions.ValidationError("请先解绑当前账号。")
            if config.device_id:
                try:
                    server_call(config, f"connector/{config.device_id}/", {"action": "revoke"})
                except exceptions.ValidationError:
                    # An expired, unconfirmed grant can never connect.
                    if config.pairing_expires_at and config.pairing_expires_at > timezone.now():
                        raise
            code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            token = secrets.token_urlsafe(48)
            config.credentials = encrypt_credentials({"device_token": token, "local_token": secrets.token_urlsafe(48)})
            result = server_call(config, "pairings/", {
                "code": code, "token": token, "name": config.computer_name,
            })
            config.device_id = result["id"]
            config.pairing_code = code
            config.pairing_expires_at = timezone.now() + timedelta(seconds=result["expires_in"])
        elif action == "pending":
            if not config.device_id:
                return Response({"account": None})
            return Response(server_call(config, f"connector/{config.device_id}/", method="GET"))
        elif action == "confirm":
            if not config.device_id or not request.data.get("account_id"):
                raise exceptions.ValidationError("没有待确认的账号。")
            result = server_call(config, f"connector/{config.device_id}/", {
                "action": "confirm", "account_id": request.data["account_id"],
            })
            config.bound_account = result["account"]
            config.pairing_code = ""
        elif action == "unbind":
            if config.device_id:
                try:
                    server_call(config, f"connector/{config.device_id}/", {"action": "revoke"})
                except DeviceCredentialExpired:
                    pass
                except exceptions.ValidationError:
                    config.enabled = False
                    config.status = "disabled"
                    save_local_action(config, original, force_fields=("enabled", "status"))
                    return Response({"detail": "本机已停止远程访问。服务器暂不可用，请恢复网络后再次解绑以撤销服务器凭证。"}, status=503)
            config.enabled = False
            config.device_id = None
            config.credentials = config.bound_account = config.pairing_code = ""
            config.pairing_expires_at = None
            config.status = "disabled"
        elif action != "reconnect":
            raise exceptions.NotFound()
        save_local_action(config, original, force_fields=("enabled", "status") if action == "unbind" else ())
        return Response(config_data(config))


class LocalContextView(APIView):
    def get(self, request):
        if not getattr(request, "remote_connector", False):
            raise exceptions.PermissionDenied()
        config = local_config()
        from .terminal_process import terminal_capability
        return Response({"organization_id": str(config.organization_id), "computer_name": config.computer_name,
                         "terminal": {**terminal_capability(), "enabled": config.terminal_enabled},
                         "files": {"supported": True, "enabled": config.file_transfer_enabled,
                                   "max_file_size": 2 * 1024**3, "chunk_size": 256 * 1024}})


class PairingThrottle(AnonRateThrottle):
    rate = "10/hour"


class ClaimThrottle(UserRateThrottle):
    rate = "10/minute"


class PairingInput(serializers.Serializer):
    code = serializers.RegexField(r"^[A-HJ-NP-Z2-9]{8}$")
    token = serializers.CharField(min_length=40, max_length=100)
    name = serializers.CharField(max_length=100)


class PairingView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PairingThrottle]

    def post(self, request):
        require_relay()
        serializer = PairingInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        hashed = digest(data["code"])
        RemoteDevice.objects.filter(pairing_expires_at__lte=timezone.now(), confirmed=False).update(pairing_hash=None)
        if RemoteDevice.objects.filter(pairing_hash=hashed).exists():
            raise exceptions.ValidationError("配对码冲突，请重试。")
        device = RemoteDevice.objects.create(
            name=data["name"], token_hash=digest(data["token"]), pairing_hash=hashed,
            pairing_expires_at=timezone.now() + timedelta(minutes=10),
        )
        return Response({"id": str(device.id), "expires_in": 600}, status=201)


class ClaimView(APIView):
    throttle_classes = [ClaimThrottle]

    @transaction.atomic
    def post(self, request):
        require_relay()
        code = str(request.data.get("code", "")).strip().upper().replace("-", "")
        device = RemoteDevice.objects.select_for_update().filter(
            pairing_hash=digest(code), owner__isnull=True, confirmed=False,
            revoked_at__isnull=True, pairing_expires_at__gt=timezone.now(),
        ).first()
        if not device:
            raise exceptions.ValidationError("配对码无效、已使用或已过期。")
        device.owner = request.user
        device.pairing_hash = None
        device.save(update_fields=["owner", "pairing_hash"])
        return Response({"id": str(device.id), "name": device.name, "status": "awaiting_confirmation"})


class ConnectorControlView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        # Device authentication runs below rather than in an authentication
        # class. Without a challenge DRF rewrites AuthenticationFailed to 403,
        # preventing the computer from clearing an already revoked binding.
        return 'Device realm="remote-connector"'

    def device(self, request, device_id):
        require_relay()
        token = request.headers.get("Authorization", "").removeprefix("Device ")
        return authenticate_device(device_id, token)

    def get(self, request, device_id):
        device = self.device(request, device_id)
        return Response({"account": device.owner.username if device.owner else None,
                         "account_id": device.owner_id, "confirmed": device.confirmed})

    @transaction.atomic
    def post(self, request, device_id):
        self.device(request, device_id)
        device = RemoteDevice.objects.select_for_update().get(pk=device_id)
        if request.data.get("action") == "revoke":
            device.revoked_at = timezone.now()
            device.session_id = ""
            device.pairing_hash = None
        elif request.data.get("action") == "confirm":
            if (not device.owner or not device.owner.is_active or device.revoked_at
                    or str(device.owner_id) != str(request.data.get("account_id"))):
                raise exceptions.ValidationError("绑定账号已变化，请重新核对。")
            device.confirmed = True
            device.pairing_hash = None
        else:
            raise exceptions.ValidationError("Unknown connector action")
        device.save()
        return Response({"account": device.owner.username if device.owner else None, "confirmed": device.confirmed})


class DeviceListView(APIView):
    def get(self, request):
        require_relay()
        devices = RemoteDevice.objects.filter(owner=request.user, revoked_at__isnull=True).order_by("-created_at")
        return Response([{
            "id": str(device.id), "name": device.name, "online": device.online,
            "confirmed": device.confirmed, "last_seen_at": device.last_seen_at,
        } for device in devices])


class DeviceView(APIView):
    def delete(self, request, device_id):
        require_relay()
        device = get_object_or_404(RemoteDevice, pk=device_id, owner=request.user, revoked_at__isnull=True)
        device.revoked_at = timezone.now()
        device.session_id = ""
        device.pairing_hash = None
        device.save(update_fields=["revoked_at", "session_id", "pairing_hash"])
        return Response(status=204)

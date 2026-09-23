"""Recoverable per-account connector; never hold a DB transaction during HTTP."""
import uuid
from datetime import timedelta

from cryptography.fernet import InvalidToken
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.enterprise.models import Organization
from modules.execution.application.errors import DeploymentUnavailable, InvalidExecutionDefinition
from modules.tenancy.database import tenant_database_context
from .models import Binding, IncomingMessage, OutgoingMessage
from .protocol import BASE_URL, WechatClient, WechatError, seal, unseal, trusted_base
from .menu import clear_menu
from .services import active_lease, check_access, collect_results, dispatch_message, enqueue, store_updates

LOGIN_STATES = ("qr_pending", "wait", "scaned", "need_verifycode")
LEASE_SECONDS = 120


def candidates():
    # Enumerate tenants first: forced PostgreSQL RLS hides unscoped binding rows.
    for oid in Organization.objects.filter(is_active=True).values_list("id", flat=True).iterator():
        with tenant_database_context(oid):
            ids = list(Binding.objects.filter(organization_id=oid, next_poll_at__lte=timezone.now()).filter(
                Q(enabled=True) | Q(status__in=LOGIN_STATES),
            ).order_by("next_poll_at").values_list("id", flat=True))
        for bid in ids:
            yield oid, bid


def claim(binding_id, owner):
    now = timezone.now()
    return Binding.objects.filter(pk=binding_id, lease_until__lte=now).update(
        lease_owner=owner, lease_until=now + timedelta(seconds=LEASE_SECONDS), heartbeat_at=now,
    ) == 1


def renew(binding_id, owner):
    return Binding.objects.filter(pk=binding_id, lease_owner=owner, lease_until__gt=timezone.now()).update(
        lease_until=timezone.now() + timedelta(seconds=LEASE_SECONDS), heartbeat_at=timezone.now(),
    ) == 1


def login_step(snapshot, owner, client_factory=WechatClient):
    if snapshot.login_expires_at <= timezone.now():
        with tenant_database_context(snapshot.organization_id):
            Binding.objects.filter(pk=snapshot.pk, lease_owner=owner, login_id=snapshot.login_id).update(status="expired", login_data="", last_error="二维码已过期，请重新扫码。")
        return
    data = unseal(snapshot.login_data)
    client = client_factory(data.get("base_url", BASE_URL))
    if snapshot.status == "qr_pending":
        result = client.qrcode()
        if not all(isinstance(result.get(k), str) and result[k] for k in ("qrcode", "qrcode_img_content")):
            raise WechatError("微信未返回二维码，请重试。")
        data = {"qrcode": result["qrcode"], "display": result["qrcode_img_content"], "base_url": BASE_URL}
        result = {"status": "wait"}
    else:
        if snapshot.status == "need_verifycode" and not data.get("verify_code"):
            return
        result = client.login_status(data["qrcode"], data.get("verify_code", ""))
    with tenant_database_context(snapshot.organization_id), transaction.atomic():
        current = Binding.objects.select_for_update().filter(pk=snapshot.pk, lease_owner=owner, lease_until__gt=timezone.now(), login_id=snapshot.login_id, status__in=LOGIN_STATES).first()
        if not current:
            return
        check_access(current)
        status = result.get("status", "wait")
        if status == "confirmed":
            required = ("bot_token", "ilink_bot_id", "ilink_user_id", "baseurl")
            if not all(isinstance(result.get(k), str) and result[k] for k in required):
                raise WechatError("微信登录信息不完整，请重新扫码。")
            if any(len(result[k]) > 255 for k in ("ilink_bot_id", "ilink_user_id")):
                raise WechatError("微信账号标识格式异常，请重新扫码。")
            same_account = current.bot_id == result["ilink_bot_id"] and current.peer_id == result["ilink_user_id"]
            current.bot_id = result["ilink_bot_id"]
            current.peer_id = result["ilink_user_id"]
            current.credentials = seal({"token": result["bot_token"], "base_url": trusted_base(result["baseurl"])})
            if not same_account:
                current.generation = uuid.uuid4()
                current.cursor = ""
                current.conversation = None
            current.enabled = True
            clear_menu(current)
            current.status = "connecting"
            current.login_data = ""
            current.login_id = current.login_expires_at = None
        elif status == "scaned_but_redirect":
            host = result.get("redirect_host") or ""
            if not isinstance(host, str):
                raise WechatError("微信返回了无效的服务地址。")
            data["base_url"] = trusted_base(host if host.startswith("https://") else "https://" + host)
            current.status = "scaned"
            current.login_data = seal(data)
        elif status in ("expired", "verify_code_blocked", "binded_redirect"):
            current.status = "expired"
            current.login_data = ""
            current.last_error = "二维码已失效或账号已绑定其他实例，请检查微信后重新扫码。"
        elif status in ("wait", "scaned", "need_verifycode"):
            current.status = status
            # A submitted verification code is one-use. Preserve a newer code
            # submitted while this HTTP request was in flight.
            latest = unseal(current.login_data)
            if latest.get("verify_code") != data.get("verify_code"):
                data["verify_code"] = latest.get("verify_code", "")
            else:
                data.pop("verify_code", None)
            current.login_data = seal(data)
        else:
            raise WechatError("微信返回了未知登录状态，请重试。")
        current.next_poll_at = timezone.now() + timedelta(seconds=2)
        current.save()


def deliver(snapshot, owner, client):
    # Bound each pass; subsequent cycles resume in order.
    for _ in range(20):
        with tenant_database_context(snapshot.organization_id):
            if not renew(snapshot.pk, owner):
                return
            with transaction.atomic():
                binding = active_lease(snapshot.pk, owner, snapshot.generation).select_for_update().first()
                if not binding:
                    return
                check_access(binding, require_agent=False)
                reply = OutgoingMessage.objects.filter(
                    incoming__binding=binding, incoming__generation=snapshot.generation,
                    state__in=("pending", "retry", "sending"),
                ).select_related("incoming").order_by("created_at", "part").first()
                if not reply or reply.next_attempt_at > timezone.now():
                    return
                if reply.attempts >= 5:
                    reply.state = "failed"
                    reply.last_error = "回复重试已达上限，请在项目中查看结果。"
                    reply.save(update_fields=["state", "last_error"])
                    continue
                reply.attempts += 1
                reply.state = "sending"
                reply.save(update_fields=["attempts", "state"])
                context = unseal(reply.incoming.context_token)["token"]
        try:
            client.send(snapshot.peer_id, context, reply.text, str(reply.id))
        except WechatError as exc:
            with tenant_database_context(snapshot.organization_id):
                OutgoingMessage.objects.filter(pk=reply.pk, state="sending").update(
                    state="failed" if reply.attempts >= 5 else "retry",
                    next_attempt_at=timezone.now() + timedelta(seconds=min(300, 2 ** reply.attempts * 2)),
                    last_error="发送确认不明确，重试可能产生重复回复。" if exc.uncertain else str(exc),
                )
            if exc.expired:
                raise
            return
        with tenant_database_context(snapshot.organization_id):
            OutgoingMessage.objects.filter(pk=reply.pk, state="sending").update(state="sent", last_error="")
            active_lease(snapshot.pk, owner, snapshot.generation).update(sent_at=timezone.now())


def process_pending(snapshot, owner):
    with tenant_database_context(snapshot.organization_id):
        ids = list(IncomingMessage.objects.filter(binding=snapshot, generation=snapshot.generation, state="pending").values_list("id", flat=True)[:100])
    for mid in ids:
        try:
            with tenant_database_context(snapshot.organization_id):
                dispatch_message(mid, owner)
        except (DeploymentUnavailable, InvalidExecutionDefinition):
            with tenant_database_context(snapshot.organization_id), transaction.atomic():
                if not active_lease(snapshot.pk, owner, snapshot.generation).exists():
                    return
                item = IncomingMessage.objects.select_for_update().get(pk=mid)
                enqueue(item, "configuration", "智能体暂时无法执行，请在项目中检查智能体配置。")
                item.state = "handled"
                item.save(update_fields=["state"])
    with tenant_database_context(snapshot.organization_id):
        collect_results(snapshot.pk, owner, snapshot.generation)


def cycle(organization_id, binding_id, client_factory=WechatClient):
    owner = uuid.uuid4().hex
    close_old_connections()
    snapshot = None
    try:
        with tenant_database_context(organization_id):
            if not claim(binding_id, owner):
                return
            snapshot = Binding.objects.select_related("user", "organization", "application", "agent").get(pk=binding_id)
            check_access(snapshot, require_agent=False)
        if snapshot.status in LOGIN_STATES:
            login_step(snapshot, owner, client_factory)
            return
        if not snapshot.enabled:
            return
        credentials = unseal(snapshot.credentials)
        client = client_factory(credentials["base_url"], credentials["token"])
        process_pending(snapshot, owner)
        deliver(snapshot, owner, client)
        with tenant_database_context(organization_id):
            if not active_lease(snapshot.pk, owner, snapshot.generation).exists() or not renew(snapshot.pk, owner):
                return
        data = client.updates(snapshot.cursor)
        with tenant_database_context(organization_id):
            store_updates(snapshot.pk, owner, snapshot.generation, data)
        process_pending(snapshot, owner)
        deliver(snapshot, owner, client)
    except (WechatError, InvalidToken, IntegrityError, ValidationError) as exc:
        if snapshot is not None:
            with tenant_database_context(organization_id):
                updates = {"last_error": str(exc) if isinstance(exc, WechatError) else "绑定或权限不可用，请检查配置或重新扫码。", "next_poll_at": timezone.now() + timedelta(seconds=15)}
                if isinstance(exc, InvalidToken) or (isinstance(exc, WechatError) and exc.expired):
                    updates.update(status="expired", enabled=False, login_data="")
                elif isinstance(exc, (ValidationError, IntegrityError)):
                    updates.update(status="blocked", enabled=False, login_data="")
                elif snapshot.status not in LOGIN_STATES:
                    updates["status"] = "reconnecting"
                Binding.objects.filter(pk=binding_id, lease_owner=owner, generation=snapshot.generation, login_id=snapshot.login_id).update(**updates)
    finally:
        with tenant_database_context(organization_id):
            Binding.objects.filter(pk=binding_id, lease_owner=owner, next_poll_at__lte=timezone.now()).update(next_poll_at=timezone.now() + timedelta(seconds=1))
            Binding.objects.filter(pk=binding_id, lease_owner=owner).update(lease_owner="", lease_until=timezone.now())
        close_old_connections()

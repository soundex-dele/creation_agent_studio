"""Tenant-local persistence and dispatch. Network I/O belongs to the connector."""
import hashlib
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from apps.conversations.execution import ConversationRunActive, create_conversation_run, resolve_agent, ensure_supervisor_access
from apps.conversations.models import Conversation
from apps.enterprise.models import Membership
from core.resource_access import can_access_resource
from modules.execution.models import Run
from .models import Binding, IncomingMessage, OutgoingMessage
from .protocol import seal

ACTIVE = ("queued", "running", "waiting_input", "waiting_children", "cancelling")
BUSY = "当前任务尚未完成，请在项目中处理后重试。"


def check_access(binding, *, require_agent=True):
    if (not binding.user.is_active or not binding.organization.is_active
            or not binding.application.is_active
            or binding.application.organization_id != binding.organization_id
            or binding.application.slug != "wechat-assistant"
            or not Membership.objects.filter(user=binding.user, organization=binding.organization, is_active=True).exists()
            or not can_access_resource(binding.application, binding.user, operation="run")):
        raise ValidationError("当前账号已无权使用微信助手。")
    if require_agent:
        if not binding.agent_id:
            raise ValidationError("请先选择智能体。")
        agent = resolve_agent(binding.agent_id, binding.organization, binding.user)
        ensure_supervisor_access(agent, binding.user)
        return agent


def is_busy(binding):
    if not binding.conversation_id:
        return False
    cid = str(binding.conversation_id)
    return Run.objects.for_organization(binding.organization_id).filter(
        Q(source_type="conversation", source_id=cid)
        | Q(source_type__in=("supervisor", "supervisor_task"), definition_snapshot__conversation_id=cid),
        status__in=ACTIVE,
    ).exists()


def new_conversation(binding):
    binding.conversation = Conversation.objects.create(
        user=binding.user, organization=binding.organization, agent=binding.agent,
        agent_locked=True, title="微信对话",
    )
    binding.save(update_fields=["conversation", "updated_at"])
    return binding.conversation


@transaction.atomic
def configure(binding, agent_id=None, *, reset=False):
    binding = Binding.objects.select_for_update().get(pk=binding.pk)
    check_access(binding, require_agent=False)
    if is_busy(binding):
        raise ValidationError(BUSY)
    if agent_id is not None:
        agent = resolve_agent(agent_id, binding.organization, binding.user)
        ensure_supervisor_access(agent, binding.user)
        if binding.agent_id != agent.id:
            binding.agent = agent
            binding.save(update_fields=["agent", "updated_at"])
            reset = True
    if reset:
        check_access(binding)
        new_conversation(binding)
    return binding


@transaction.atomic
def start_login(binding):
    binding = Binding.objects.select_for_update().get(pk=binding.pk)
    check_access(binding)
    if is_busy(binding):
        raise ValidationError(BUSY)
    if binding.enabled:
        raise ValidationError("请先解绑当前微信再扫码；临时断线请使用重新连接。")
    binding.login_id = uuid.uuid4()
    binding.login_data = ""
    binding.login_expires_at = timezone.now() + timedelta(minutes=5)
    binding.status = "qr_pending"
    binding.next_poll_at = timezone.now()
    binding.last_error = ""
    binding.save()
    return binding


@transaction.atomic
def unbind(binding):
    binding = Binding.objects.select_for_update().get(pk=binding.pk)
    binding.enabled = False
    binding.status = "unbound"
    binding.credentials = binding.peer_id = binding.cursor = binding.login_data = ""
    binding.bot_id = binding.login_id = binding.login_expires_at = None
    binding.generation = uuid.uuid4()
    binding.conversation = None
    binding.last_error = ""
    binding.save()
    IncomingMessage.objects.filter(binding=binding, state="pending").update(state="discarded")
    OutgoingMessage.objects.filter(incoming__binding=binding).exclude(state="sent").update(state="discarded")
    return binding


def enqueue(incoming, event_key, text):
    # Conservative text chunks, stable IDs and ordering across process restarts.
    for part, start in enumerate(range(0, len(text), 1000)):
        OutgoingMessage.objects.get_or_create(
            incoming=incoming, event_key=event_key, part=part,
            defaults={"organization_id": incoming.organization_id, "text": text[start:start + 1000]},
        )


def active_lease(binding_id, owner, generation):
    return Binding.objects.filter(pk=binding_id, lease_owner=owner, lease_until__gt=timezone.now(), generation=generation, enabled=True)


@transaction.atomic
def store_updates(binding_id, owner, generation, data):
    binding = active_lease(binding_id, owner, generation).select_for_update().first()
    if not binding:
        return
    now = timezone.now()
    for msg in data.get("msgs") or []:
        if not isinstance(msg, dict) or msg.get("message_type") != 1 or msg.get("group_id"):
            continue
        if msg.get("from_user_id") != binding.peer_id or str(msg.get("to_user_id") or binding.bot_id) != binding.bot_id:
            continue
        mid = str(msg.get("message_id") or "")
        context = msg.get("context_token")
        if not mid or len(mid) > 255 or not isinstance(context, str) or not context:
            continue
        items = msg.get("item_list") or []
        supported = bool(items) and all(isinstance(i, dict) and i.get("type") == 1 for i in items)
        text = "\n".join(str((i.get("text_item") or {}).get("text") or "") for i in items if isinstance(i, dict) and i.get("type") == 1)
        # Namespace by bot identity so reauthorizing/rebinding the same bot
        # cannot execute an already persisted upstream message again.
        dedup_id = hashlib.sha256(f"{binding.bot_id}:{mid}".encode()).hexdigest()
        IncomingMessage.objects.get_or_create(
            binding=binding, message_id=dedup_id,
            defaults={"organization_id": binding.organization_id, "text": text,
                      "generation": generation, "supported": supported, "context_token": seal({"token": context})},
        )
        binding.received_at = now
    cursor = data.get("get_updates_buf")
    if isinstance(cursor, str) and cursor:
        binding.cursor = cursor
    binding.heartbeat_at = now
    binding.status = "connected"
    binding.last_error = ""
    binding.save(update_fields=["cursor", "received_at", "heartbeat_at", "status", "last_error", "updated_at"])


@transaction.atomic
def dispatch_message(message_id, owner):
    item = IncomingMessage.objects.select_related("binding").get(pk=message_id)
    binding = active_lease(item.binding_id, owner, item.generation).select_for_update().first()
    if not binding:
        return
    item = IncomingMessage.objects.select_for_update().get(pk=item.pk)
    if item.state != "pending":
        return
    try:
        check_access(binding)
        if not item.supported or not item.text.strip():
            enqueue(item, "unsupported", "微信助手首版仅支持文本私聊，请发送文字。")
        elif len(item.text) > 32000:
            enqueue(item, "too-long", "消息过长，请缩短后重新发送。")
        else:
            if not binding.conversation_id:
                new_conversation(binding)
            item.conversation = binding.conversation
            item.run, _ = create_conversation_run(
                binding.user, binding.conversation, item.text, f"wechat:{item.id}",
            )
    except ConversationRunActive:
        enqueue(item, "busy", BUSY)
    except Throttled:
        enqueue(item, "quota", "当前执行额度或并发数已达上限，请在项目中检查后重试。")
    except (PermissionDenied, DjangoPermissionDenied):
        enqueue(item, "policy", "本次请求未通过组织执行策略，请在项目中检查权限和配置。")
    except ValidationError:
        binding.last_error = "账号、应用或智能体权限不可用，请在项目中检查配置。"
        binding.save(update_fields=["last_error", "updated_at"])
        enqueue(item, "rejected", binding.last_error)
    item.state = "running" if item.run_id else "handled"
    item.save(update_fields=["state", "run", "conversation"])


def conversation_hint(item):
    hint = "请打开项目中的微信助手，进入对应会话处理。"
    base = getattr(settings, "WECHAT_ASSISTANT_PUBLIC_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if base and parsed.scheme == "https" and parsed.hostname and parsed.hostname not in ("localhost", "127.0.0.1", "::1") and not parsed.username and not parsed.password:
        hint += f"\n{base}/chat?conversation={item.conversation_id}"
    return hint


@transaction.atomic
def collect_results(binding_id, owner, generation):
    binding = active_lease(binding_id, owner, generation).select_for_update().first()
    if not binding:
        return
    for item in IncomingMessage.objects.filter(binding=binding, generation=generation, state="running").select_related("run"):
        run = item.run
        if run.status == "waiting_input":
            enqueue(item, f"input:{run.pending_input_request_id}", "任务需要补充信息或批准操作。" + conversation_hint(item))
        elif run.status not in ACTIVE:
            text = {"succeeded": str((run.output_summary or {}).get("result") or "任务已完成，请在项目会话中查看结果。"),
                    "failed": "任务执行失败，请在项目会话中查看详情。", "cancelled": "任务已取消。"}.get(run.status, "任务已结束，请在项目中查看详情。")
            enqueue(item, "terminal", text)
            item.state = "handled"
            item.save(update_fields=["state"])

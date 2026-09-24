import asyncio
import json
import time
import uuid

from channels.db import database_sync_to_async
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException

from .broker import Subscription, publish
from .models import RemoteDevice
from .protocol import VERSION, MAX_BODY, MAX_CHUNK, MAX_INFLIGHT, OFFLINE_AFTER
from .security import authenticate_device


async def connector_socket(scope, receive, send):
    """Authenticated computer socket; browser Origin and query credentials refused."""
    headers = dict(scope.get("headers", []))
    if (not settings.REMOTE_RELAY_ENABLED or b"origin" in headers or scope.get("query_string")):
        await send({"type": "websocket.close", "code": 4403})
        return
    try:
        device_id = uuid.UUID(headers.get(b"x-device-id", b"").decode())
        token = headers.get(b"authorization", b"").decode().removeprefix("Device ")
        device = await database_sync_to_async(authenticate_device)(device_id, token, paired=True)
    except (ValueError, APIException):
        await send({"type": "websocket.close", "code": 4401})
        return
    if (await receive())["type"] != "websocket.connect":
        return
    session = uuid.uuid4().hex
    topic = f"device:{device.id}:{session}"
    subscription = Subscription(topic)
    pending = set()
    last_heartbeat = time.monotonic()
    tasks = []

    async def wire(message):
        await send({"type": "websocket.send", "text": json.dumps({"v": VERSION, **message})})

    async def incoming():
        nonlocal last_heartbeat
        while True:
            frame = await receive()
            if frame["type"] == "websocket.disconnect":
                return
            raw = frame.get("text", "")
            if len(raw) > MAX_BODY:
                return
            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                return
            if not isinstance(message, dict) or message.get("v") != VERSION:
                return
            kind, request_id = message.get("type"), message.get("id")
            if kind == "ping":
                last_heartbeat = time.monotonic()
                await RemoteDevice.objects.filter(pk=device.id, session_id=session).aupdate(last_seen_at=timezone.now())
                await wire({"type": "pong"})
            elif kind == "hello" and isinstance(message.get("name"), str) and 0 < len(message["name"]) <= 100:
                await RemoteDevice.objects.filter(pk=device.id, session_id=session).aupdate(name=message["name"])
            elif request_id in pending and kind in {"start", "chunk", "end", "error"}:
                if kind == "chunk" and len(message.get("body", "")) > MAX_CHUNK * 2:
                    return
                await publish(f"response:{request_id}", message)
                if kind in {"end", "error"}:
                    pending.discard(request_id)
            elif kind not in {"start", "chunk", "end", "error"}:
                return

    async def outgoing():
        while True:
            try:
                message = await subscription.receive()
            except TimeoutError:
                continue
            kind, request_id = message.get("type"), message.get("id")
            if kind == "request":
                if len(pending) >= MAX_INFLIGHT:
                    await publish(f"response:{request_id}", {"type": "error", "detail": "电脑连接繁忙，请稍后重试。"})
                    continue
                pending.add(request_id)
            elif kind == "cancel":
                pending.discard(request_id)
            elif kind == "ack":
                if request_id not in pending:
                    continue
            else:
                return
            await wire(message)

    async def watchdog():
        while True:
            await asyncio.sleep(1)
            if time.monotonic() - last_heartbeat >= OFFLINE_AFTER:
                return
            if not await RemoteDevice.objects.filter(
                    pk=device.id, session_id=session, revoked_at__isnull=True,
                    owner__is_active=True, confirmed=True).aexists():
                await wire({'type': 'revoked'})
                return

    try:
        await subscription.open()
        await RemoteDevice.objects.filter(pk=device.id, revoked_at__isnull=True).aupdate(
            session_id=session, last_seen_at=timezone.now())
        await send({"type": "websocket.accept"})
        await wire({"type": "ready"})
        tasks = [asyncio.create_task(coro()) for coro in (incoming, outgoing, watchdog)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for request_id in pending:
            await publish(f"response:{request_id}", {"type": "error", "detail": "电脑已离线，请使用原请求重试。"})
        await subscription.close()
        await RemoteDevice.objects.filter(pk=device.id, session_id=session).aupdate(session_id="")
        await send({"type": "websocket.close", "code": 1000})

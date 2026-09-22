"""Managed process. No request handler or import starts threads or connections."""
import asyncio
import base64
import json
import random
import time
from urllib.parse import urlsplit

import httpx
from channels.db import database_sync_to_async
from django.conf import settings
from django.utils import timezone
from websockets.asyncio.client import connect

from .models import LocalRemoteConfig
from .protocol import HEARTBEAT, MAX_BODY, MAX_CHUNK, MAX_INFLIGHT, VERSION, validate_request
from .security import authorized_user, decrypt_credentials


@database_sync_to_async
def read_config():
    config, _ = LocalRemoteConfig.objects.select_related("local_user", "organization").get_or_create(pk=1)
    if config.enabled and config.bound_account:
        authorized_user(config)
    return config


async def report(status):
    await LocalRemoteConfig.objects.filter(pk=1).aupdate(status=status, connector_seen_at=timezone.now())


def local_origin():
    value = settings.REMOTE_CONNECTOR_LOCAL_URL.rstrip("/")
    url = urlsplit(value)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username or url.password or url.path or url.query or url.fragment):
        raise ValueError("REMOTE_CONNECTOR_LOCAL_URL must be a loopback HTTP origin")
    return value


async def run_connection(config):
    credentials = decrypt_credentials(config.credentials)
    endpoint = config.server_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    tasks = {}
    credits = {}
    background = []
    last_pong = time.monotonic()
    async with httpx.AsyncClient(base_url=local_origin(), trust_env=False, follow_redirects=False,
                                timeout=httpx.Timeout(60, connect=5)) as client:
        # Do not advertise a computer whose API is not running.
        (await client.get("/healthz/")).raise_for_status()
        async with connect(endpoint + "/ws/remote/connector/", additional_headers={
            "Authorization": "Device " + credentials["device_token"],
            "X-Device-ID": str(config.device_id),
        }, max_size=MAX_BODY * 2, max_queue=16, proxy=None, open_timeout=10, ping_interval=HEARTBEAT) as socket:
            async def wire(frame):
                await socket.send(json.dumps({"v": VERSION, **frame}, separators=(",", ":")))

            async def handle(frame):
                request_id = frame["id"]
                try:
                    current = await read_config()
                    if not current.enabled or current.revision != config.revision:
                        raise ValueError("Local grant changed")
                    validate_request(frame["method"], frame["path"], frame.get("body"), config.organization_id)
                    headers = {"Authorization": "RemoteLocal " + credentials["local_token"],
                               "X-Organization-ID": str(config.organization_id),
                               "Idempotency-Key": frame.get("idempotency_key", "")}
                    async with client.stream(frame["method"], frame["path"],
                                             json=frame.get("body") if frame["method"] == "POST" else None,
                                             headers=headers) as response:
                        await wire({"type": "start", "id": request_id, "status": response.status_code,
                                    "content_type": response.headers.get("content-type", "application/json")})
                        # aiter_bytes without chunk_size emits SSE immediately instead of
                        # waiting for a 32 KiB buffer to fill.
                        async for block in response.aiter_bytes():
                            for offset in range(0, len(block), MAX_CHUNK):
                                credits[request_id].clear()
                                await wire({"type": "chunk", "id": request_id,
                                            "body": base64.b64encode(block[offset:offset + MAX_CHUNK]).decode()})
                                await asyncio.wait_for(credits[request_id].wait(), 60)
                        await wire({"type": "end", "id": request_id})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Never include local URLs, response bodies or exception text.
                    await wire({"type": "error", "id": request_id, "detail": "本机请求失败，请检查权限、许可证与连接。"})
                finally:
                    tasks.pop(request_id, None)
                    credits.pop(request_id, None)

            async def incoming():
                nonlocal last_pong
                async for raw in socket:
                    frame = json.loads(raw)
                    if frame.get("v") != VERSION:
                        raise ValueError("Unsupported relay protocol")
                    kind, request_id = frame.get("type"), frame.get("id")
                    if kind == "ready":
                        await report("online")
                        await wire({"type": "hello", "name": config.computer_name})
                    elif kind == "pong":
                        last_pong = time.monotonic()
                    elif kind == "request":
                        if not isinstance(request_id, str) or len(request_id) != 32 or request_id in tasks:
                            raise ValueError("Invalid request identifier")
                        if len(tasks) >= MAX_INFLIGHT:
                            await wire({"type": "error", "id": request_id, "detail": "电脑连接繁忙。"})
                            continue
                        credits[request_id] = asyncio.Event()
                        tasks[request_id] = asyncio.create_task(handle(frame))
                    elif kind == "ack" and request_id in credits:
                        credits[request_id].set()
                    elif kind == "cancel" and request_id in tasks:
                        # Cancel only this HTTP subscription, never a business Run.
                        tasks[request_id].cancel()

            async def heartbeat():
                while True:
                    await wire({"type": "ping"})
                    await asyncio.sleep(HEARTBEAT)
                    if time.monotonic() - last_pong >= 60:
                        return

            async def monitor():
                while True:
                    await asyncio.sleep(1)
                    current = await read_config()
                    if not current.enabled or current.revision != config.revision:
                        return
                    (await client.get("/healthz/", timeout=2)).raise_for_status()
                    await report("online")

            try:
                background = [asyncio.create_task(fn()) for fn in (incoming, heartbeat, monitor)]
                done, _ = await asyncio.wait(background, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                remaining = [*background, *tasks.values()]
                for task in remaining:
                    task.cancel()
                await asyncio.gather(*remaining, return_exceptions=True)


async def run_connector():
    delay = 1
    while True:
        config = None
        try:
            config = await read_config()
            if not config.enabled or not config.device_id or not config.bound_account:
                await report("unpaired" if config.enabled else "disabled")
                delay = 1
                await asyncio.sleep(1)
                continue
            await report("connecting")
            started = time.monotonic()
            await run_connection(config)
            if time.monotonic() - started > 60:
                delay = 1
        except asyncio.CancelledError:
            raise
        except Exception:
            await report("reconnecting")
        # Configuration changes interrupt the backoff promptly.
        for _ in range(max(1, int(delay + random.random()))):
            await asyncio.sleep(1)
            try:
                current = await read_config()
                await report("reconnecting" if current.enabled else "disabled")
                if config is None or not current.enabled or current.revision != config.revision:
                    break
            except Exception:
                break
        delay = min(delay * 2, 30)

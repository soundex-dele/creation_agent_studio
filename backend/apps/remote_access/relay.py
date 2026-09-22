import asyncio
import base64
import json
import uuid

from asgiref.sync import sync_to_async
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import exceptions
from rest_framework.views import APIView

from modules.execution.api.renderers import EventStreamRenderer

from .broker import Subscription, publish
from .models import RemoteDevice
from .protocol import MAX_BODY, MAX_CHUNK, validate_request
from .views import require_relay


def authorize(request, device_id):
    require_relay()
    view = APIView()
    # initial() negotiates content before checking authentication. Admit the
    # browser's SSE Accept header; the proxied response provides the actual body.
    view.renderer_classes = [*view.renderer_classes, EventStreamRenderer]
    drf_request = view.initialize_request(request)
    view.initial(drf_request)
    device = RemoteDevice.objects.filter(pk=device_id, owner=drf_request.user, revoked_at__isnull=True).first()
    if not device:
        raise exceptions.NotFound()
    if not device.online:
        raise exceptions.APIException("电脑已离线，指令未发送。", code="computer_offline")
    return f"device:{device.id}:{device.session_id}"


@csrf_exempt
async def proxy(request, device_id, target):
    subscription = None
    request_id = uuid.uuid4().hex
    topic = None
    dispatched = False
    try:
        topic = await sync_to_async(authorize, thread_sensitive=True)(request, device_id)
        if len(request.body) > MAX_BODY:
            return JsonResponse({"detail": "Remote request is too large"}, status=413)
        body = json.loads(request.body) if request.body else None
        if request.method == "POST" and request.content_type != "application/json":
            return JsonResponse({"detail": "Remote requests require JSON"}, status=415)
        path = "/api/v1/" + target
        if request.META.get("QUERY_STRING"):
            path += "?" + request.META["QUERY_STRING"]
        validate_request(request.method, path, body)
        idempotency_key = request.headers.get("Idempotency-Key", "")
        if request.method == "POST" and not path.endswith("/commands"):
            if not idempotency_key or len(idempotency_key) > 160:
                raise ValueError("Idempotency-Key is required")
        subscription = await Subscription(f"response:{request_id}").open()
        delivered = await publish(topic, {
            "type": "request", "id": request_id, "method": request.method,
            "path": path, "body": body, "idempotency_key": idempotency_key,
        })
        dispatched = bool(delivered)
        if not delivered:
            raise ConnectionError("电脑连接已中断，指令未发送。")
        first = await subscription.receive(timeout=15)
        if first.get("type") != "start":
            raise ConnectionError(first.get("detail", "电脑未响应，请使用原请求重试。"))
        status = first.get("status")
        if not isinstance(status, int) or not 200 <= status <= 599:
            raise ValueError("Invalid remote response status")
        content_type = first.get("content_type", "application/json")
        if content_type.split(";", 1)[0] not in {"application/json", "application/problem+json", "text/event-stream"}:
            raise ValueError("Unsupported remote response type")
    except (exceptions.APIException, ValueError, ConnectionError, TimeoutError) as exc:
        if subscription:
            await subscription.close()
        if topic and dispatched:
            await publish(topic, {"type": "cancel", "id": request_id})
        status = exc.status_code if isinstance(exc, exceptions.APIException) else 400 if isinstance(exc, ValueError) else 503
        if status == 500:
            status = 503
        return JsonResponse({"detail": str(exc)}, status=status)
    except BaseException:
        if subscription:
            await subscription.close()
        if topic and dispatched:
            await publish(topic, {"type": "cancel", "id": request_id})
        raise

    async def chunks():
        try:
            while True:
                frame = await subscription.receive()
                if frame.get("type") == "end":
                    break
                if frame.get("type") != "chunk":
                    raise ConnectionError("Remote subscription interrupted")
                data = base64.b64decode(frame.get("body", ""), validate=True)
                if len(data) > MAX_CHUNK:
                    raise ConnectionError("Remote chunk exceeds limit")
                yield data
                # One outstanding chunk per request gives slow clients bounded memory.
                await publish(topic, {"type": "ack", "id": request_id})
        finally:
            await publish(topic, {"type": "cancel", "id": request_id})
            await subscription.close()

    response = StreamingHttpResponse(chunks(), status=status, content_type=content_type)
    response["Cache-Control"] = "no-store"
    response["X-Accel-Buffering"] = "no"
    # Local authentication errors must not log the phone out of its server account.
    if status == 401:
        response.status_code = 403
    return response

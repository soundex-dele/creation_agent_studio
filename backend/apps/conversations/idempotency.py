"""Atomically persist conversation creation with its replay response."""
import hashlib
import json
import time
from datetime import timedelta
from functools import wraps

from django.db import OperationalError, transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer

from apps.enterprise.permissions import resolve_organization
from modules.execution.models import IdempotencyRecord


def idempotent_creation(callback):
    @wraps(callback)
    def create(view, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key", "")
        if not key:
            return callback(view, request, *args, **kwargs)
        if len(key) > 160 or not key.strip():
            return Response({"detail": "Invalid Idempotency-Key"}, status=400)
        organization = resolve_organization(request)
        if organization is None:
            return Response({"detail": "没有可用的组织工作区。"}, status=403)
        fingerprint = hashlib.sha256(json.dumps(request.data, sort_keys=True, default=str).encode()).hexdigest()
        for attempt in range(6):
            try:
                with transaction.atomic():
                    record, created = IdempotencyRecord.objects.get_or_create(
                        organization=organization, actor=request.user,
                        operation="conversation.create", key=key,
                        defaults={"request_fingerprint": fingerprint,
                                  "expires_at": timezone.now() + timedelta(hours=24)},
                    )
                    if not created:
                        if record.request_fingerprint != fingerprint:
                            return Response({"detail": "幂等键已用于不同的对话请求。"}, status=409)
                        response = Response(record.response_body, status=record.response_status)
                        response["Idempotent-Replay"] = "true"
                        return response
                    response = callback(view, request, *args, **kwargs)
                    if response.status_code >= 400:
                        transaction.set_rollback(True)
                        return response
                    record.status = IdempotencyRecord.Status.COMPLETED
                    record.response_status = response.status_code
                    record.response_body = json.loads(JSONRenderer().render(response.data))
                    record.save(update_fields=["status", "response_status", "response_body"])
                    return response
            except OperationalError as exc:
                if attempt == 5 or not any(word in str(exc).lower() for word in ("locked", "busy")):
                    raise
                time.sleep(0.02 * 2 ** attempt)
    return create

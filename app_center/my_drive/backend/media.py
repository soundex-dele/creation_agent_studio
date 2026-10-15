import asyncio
import re
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.handlers.asgi import ASGIRequest
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from .access import application_for
from .models import DriveEntry
from .storage import object_path

MEDIA_SALT = "my-drive-content-v1"
SAFE_IMAGES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "image/bmp"}
SAFE_AV = {"video/mp4", "video/webm", "video/ogg", "video/quicktime", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-wav", "audio/webm", "audio/flac"}


def preview_kind(entry):
    if entry.media_type in SAFE_IMAGES:
        return "image"
    if entry.media_type in SAFE_AV:
        return entry.media_type.split("/")[0]
    if entry.media_type in {"text/plain", "text/markdown", "application/json", "text/csv"}:
        return "text"
    return "unsupported"


def byte_range(header, size):
    if not header:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()) or not size:
        raise ValueError("Invalid range")
    first, last = match.groups()
    if not first:
        length = int(last)
        if length <= 0:
            raise ValueError("Invalid suffix")
        return max(0, size - length), size - 1, True
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable range")
    return start, end, True


def stream_file(path, start, length):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining:
            chunk = handle.read(min(256 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


async def stream_file_async(path, start, length):
    # A sync iterator under Django ASGI is materialized in memory. Always give
    # ASGI an async iterator, and keep blocking disk reads off its event loop.
    handle = await asyncio.to_thread(path.open, "rb")
    try:
        await asyncio.to_thread(handle.seek, start)
        remaining = length
        while remaining:
            chunk = await asyncio.to_thread(handle.read, min(256 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()


class ContentView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    # Media seeking can issue many ranges. Each request validates a signed
    # capability; do not charge these against the anonymous REST login budget.
    throttle_classes = []
    http_method_names = ["get", "head", "options"]

    def get(self, request, organization_id, application_id, **kwargs):
        try:
            payload = signing.loads(request.query_params.get("token", ""), salt=MEDIA_SALT,
                max_age=settings.MY_DRIVE_ACCESS_TTL_SECONDS)
            if payload["organization"] != str(organization_id) or payload["application"] != application_id:
                raise ValueError()
            if payload["mode"] not in {"preview", "download"}:
                raise ValueError()
            user = get_user_model().objects.get(pk=payload["user"], is_active=True)
        except (signing.BadSignature, ValueError, KeyError, TypeError, get_user_model().DoesNotExist):
            raise PermissionDenied("访问凭据无效或已过期，请重新打开文件。")
        app = application_for(user, organization_id, application_id)
        entry = get_object_or_404(DriveEntry, pk=payload["entry"], space__organization_id=organization_id,
            space__owner=user, application=app, kind="file", trash_batch=None, purge_pending=False)
        path = object_path(entry.object_key)
        if not path.is_file():
            from rest_framework.exceptions import NotFound
            raise NotFound("文件暂不可用。")
        download = payload["mode"] == "download"
        kind = preview_kind(entry)
        if not download and kind == "unsupported":
            raise PermissionDenied("该格式只能下载。")
        size = min(entry.size, 1024 ** 2) if not download and kind == "text" else entry.size
        try:
            start, end, partial = byte_range(request.headers.get("Range"), size)
        except ValueError:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = max(0, end - start + 1)
        # Text previews must remain capped even when nginx is serving media.
        accelerated = settings.MY_DRIVE_X_ACCEL_REDIRECT and (download or kind != "text")
        content_type = "application/octet-stream" if download else "text/plain; charset=utf-8" if kind == "text" else entry.media_type
        if accelerated:
            response = HttpResponse(content_type=content_type)
            response["X-Accel-Redirect"] = "/_protected_drive/" + quote(entry.object_key, safe="/")
        elif request.method == "HEAD":
            response = HttpResponse(status=206 if partial else 200, content_type=content_type)
        else:
            source = stream_file_async if isinstance(request._request, ASGIRequest) else stream_file
            response = StreamingHttpResponse(source(path, start, length), status=206 if partial else 200, content_type=content_type)
        response["Accept-Ranges"] = "bytes"
        response["Content-Length"] = str(size if accelerated else length)
        if partial and not accelerated:
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Disposition"] = content_disposition_header(download, entry.name)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    head = get

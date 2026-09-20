"""Validated private-media delivery, optionally accelerated by Nginx."""

import mimetypes
from pathlib import PurePosixPath
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET

from .storage import MEDIA_TOKEN_SALT


def _safe_storage_name(value):
    name = str(value or "").replace("\\", "/").lstrip("/")
    path = PurePosixPath(name)
    if not name or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid media object name")
    return path.as_posix()


@require_GET
def private_media(request):
    token = request.GET.get("token", "")
    try:
        payload = signing.loads(
            token,
            salt=MEDIA_TOKEN_SALT,
            max_age=settings.MEDIA_ACCESS_TTL_SECONDS,
        )
        name = _safe_storage_name(payload.get("name"))
        download = payload.get("download") is True
        requested_filename = PurePosixPath(
            str(payload.get("filename") or name).replace("\\", "/")
        ).name
    except (signing.BadSignature, signing.SignatureExpired, ValueError, AttributeError):
        return JsonResponse({"detail": "Media URL is invalid or expired."}, status=403)

    if not default_storage.exists(name):
        return JsonResponse({"detail": "Media object not found."}, status=404)

    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    filename = requested_filename or PurePosixPath(name).name
    if settings.MEDIA_X_ACCEL_REDIRECT:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = "/_protected_media/" + quote(name, safe="/")
        response["Content-Length"] = str(default_storage.size(name))
        response["Content-Disposition"] = content_disposition_header(download, filename)
    else:
        response = FileResponse(
            default_storage.open(name, "rb"),
            content_type=content_type,
            as_attachment=download,
            filename=filename,
        )
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response

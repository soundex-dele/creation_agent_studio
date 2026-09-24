import mimetypes
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.handlers.asgi import ASGIRequest
from django.http import HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from app_center.my_drive.backend.media import byte_range, stream_file, stream_file_async
from .views import BaseView
from .access import recording_for
from .storage import object_path

SALT = "meeting-audio-v1"
TTL = 3600


class AudioAccess(BaseView):
    def post(self, request, **kwargs):
        record = self.record()
        token = signing.dumps({"record": str(record.pk), "user": request.user.pk,
            "organization": str(record.organization_id), "application": record.application_id}, salt=SALT)
        return Response({"token": token, "expires_in": TTL})


class AudioContent(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []
    http_method_names = ["get", "head", "options"]

    def get(self, request, organization_id, application_id, **kwargs):
        try:
            data = signing.loads(request.query_params.get("token", ""), salt=SALT, max_age=TTL)
            if data["organization"] != str(organization_id) or data["application"] != application_id:
                raise ValueError()
            user = get_user_model().objects.get(pk=data["user"], is_active=True)
        except (signing.BadSignature, KeyError, ValueError, TypeError, get_user_model().DoesNotExist):
            raise PermissionDenied("音频凭据已过期，请刷新播放链接。")
        record = recording_for(user, organization_id, application_id, data["record"])
        path = object_path(record.object_key)
        if not path.is_file():
            raise NotFound("音频暂不可用。")
        size = path.stat().st_size
        try:
            first, last, partial = byte_range(request.headers.get("Range"), size)
        except ValueError:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = max(0, last - first + 1)
        mime = mimetypes.guess_type(record.filename)[0] or "application/octet-stream"
        if request.method == "HEAD":
            response = HttpResponse(status=206 if partial else 200, content_type=mime)
        else:
            stream = stream_file_async if isinstance(request._request, ASGIRequest) else stream_file
            response = StreamingHttpResponse(stream(path, first, length), status=206 if partial else 200, content_type=mime)
        response["Accept-Ranges"] = "bytes"
        response["Content-Length"] = str(length)
        if partial:
            response["Content-Range"] = f"bytes {first}-{last}/{size}"
        response["Content-Disposition"] = content_disposition_header(False, record.filename)
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    head = get

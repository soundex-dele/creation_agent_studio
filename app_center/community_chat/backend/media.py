import logging
import warnings
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.handlers.asgi import ASGIRequest
from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.platform_api.media import stream_file, stream_file_async
from .models import Attachment
from .services import MAX_BYTES, attachment_data, room_for
from .views import AuthView

logger = logging.getLogger(__name__)
SALT = 'community-chat-file-v1'


def object_path(attachment_id):
    # Only model UUIDs are accepted, never user filenames or arbitrary paths.
    return Path(settings.COMMUNITY_CHAT_ROOT) / f'{attachment_id}.bin'


class UploadThrottle(UserRateThrottle):
    scope = 'community-upload'
    rate = '30/min'


class UploadView(AuthView):
    parser_classes = [MultiPartParser]
    throttle_classes = [UploadThrottle]

    def post(self, request, room_id):
        room_for(request.user, room_id)
        if int(request.META.get('CONTENT_LENGTH') or 0) > MAX_BYTES + 1024 * 1024:
            raise ValidationError('上传请求超过 100MB 文件限制。')
        uploaded = request.FILES.get('file')
        if not uploaded or uploaded.size > MAX_BYTES or uploaded.size == 0:
            raise ValidationError('请选择非空且不超过 100MB 的文件。')
        name = Path(uploaded.name.replace('\\', '/')).name[:255]
        item = Attachment(room_id=room_id, owner=request.user, name=name, size=uploaded.size)
        path = object_path(item.pk)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with path.open('xb') as handle:
                for chunk in uploaded.chunks():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValidationError('文件不能超过 100MB。')
                    handle.write(chunk)
            item.size = total
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(path) as img:
                        if img.format in {'JPEG', 'PNG', 'GIF', 'WEBP', 'BMP', 'AVIF'}:
                            mime = Image.MIME.get(img.format)
                            img.verify()
                            item.image = True
                            item.content_type = mime or 'application/octet-stream'
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                # Files remain downloadable; only verified raster images preview.
                item.image = False
            with transaction.atomic():
                room_for(request.user, room_id, lock=True)
                item.save()
        except Exception as exc:
            path.unlink(missing_ok=True)
            logger.warning('Community upload failed room=%s', room_id)
            if isinstance(exc, OSError):
                raise APIException('文件存储暂不可用，请重试。') from exc
            raise
        return Response(attachment_data(item), status=201)


def accessible_attachment(user, attachment_id):
    item = get_object_or_404(Attachment.objects.select_related('message'), pk=attachment_id)
    room_for(user, item.room_id)
    if item.message_id:
        if item.message.withdrawn:
            raise PermissionDenied('消息已撤回。')
    elif item.owner_id != user.pk:
        raise PermissionDenied('附件尚未发送。')
    return item


class AccessView(AuthView):
    def post(self, request, attachment_id):
        item = accessible_attachment(request.user, attachment_id)
        preview = request.data.get('preview') is True
        if preview and not item.image:
            raise ValidationError('该文件仅支持下载。')
        token = signing.dumps({'id': str(item.pk), 'user': request.user.pk, 'preview': preview}, salt=SALT)
        return Response({'url': '/api/v1/community-chat/content/?token=' + token})


class ContentView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        try:
            data = signing.loads(request.query_params.get('token', ''), salt=SALT, max_age=120)
            user = get_user_model().objects.get(pk=data['user'], is_active=True)
            item = accessible_attachment(user, data['id'])
        except (signing.BadSignature, ValueError, KeyError, get_user_model().DoesNotExist):
            raise PermissionDenied('文件链接无效或已过期，请重新打开。')
        preview = data.get('preview') is True and item.image
        path = object_path(item.pk)
        if not path.is_file():
            from rest_framework.exceptions import NotFound
            raise NotFound('文件不存在。')
        source = stream_file_async if isinstance(request._request, ASGIRequest) else stream_file
        response = StreamingHttpResponse(source(path, 0, item.size), content_type=item.content_type if preview else 'application/octet-stream')
        response['Content-Length'] = str(item.size)
        response['Content-Disposition'] = content_disposition_header(not preview, item.name)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Referrer-Policy'] = 'no-referrer'
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        return response

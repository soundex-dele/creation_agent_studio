import re

from django.conf import settings
from django.core import signing
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import BaseParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle

from apps.enterprise.models import Membership
from modules.tenancy.permissions import HasPathOrganizationRole
from .access import application_for, space_for
from .models import DriveUpload
from .serializers import ActionInput, EntrySerializer, FolderInput, UploadInput, UploadSerializer
from . import services
from .media import MEDIA_SALT, preview_kind


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def context(self):
        app = application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])
        return space_for(self.request.user, app.organization_id), app


def validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class EntryList(BaseView):
    def get(self, request, **kwargs):
        space, app = self.context()
        qs = services.entries(space, app).filter(purge_pending=False)
        scope = request.query_params.get("scope", "files")
        if scope not in {"files", "trash"}:
            raise ValidationError("文件范围无效。")
        search = request.query_params.get("search", "").strip()[:240]
        breadcrumbs = []
        if scope == "trash":
            qs = qs.filter(trash_root=True)
        else:
            qs = qs.filter(trash_batch=None)
            parent_id = request.query_params.get("parent") or None
            if parent_id:
                parent_id = validated(FolderInput, {"name": "_", "parent": parent_id})["parent"]
            parent = services.folder_for(qs, parent_id)
            current = parent
            while current:
                breadcrumbs.insert(0, {"id": str(current.id), "name": current.name})
                current = current.parent
            if not search:
                qs = qs.filter(parent=parent)
        if search:
            qs = qs.filter(name__icontains=search)
        kind = request.query_params.get("type", "all")
        if kind == "folder":
            qs = qs.filter(kind="folder")
        elif kind in {"image", "video", "audio"}:
            qs = qs.filter(kind="file", media_type__startswith=kind + "/")
        elif kind == "other":
            qs = qs.filter(kind="file").exclude(Q(media_type__startswith="image/") | Q(media_type__startswith="video/") | Q(media_type__startswith="audio/"))
        elif kind != "all":
            raise ValidationError("文件类型无效。")
        order = request.query_params.get("sort", "-updated_at")
        if order not in {"name", "-name", "size", "-size", "updated_at", "-updated_at"}:
            raise ValidationError("排序无效。")
        pager = PageNumberPagination()
        pager.page_size = 50
        results = pager.paginate_queryset(qs.order_by("-kind", order, "id"), request)
        return Response({"count": pager.page.paginator.count, "results": EntrySerializer(results, many=True).data,
                         "breadcrumbs": breadcrumbs, "capacity": services.usage(space)})

    def post(self, request, **kwargs):
        space, app = self.context()
        entry = services.create_folder(space, app, validated(FolderInput, request.data))
        return Response(EntrySerializer(entry).data, status=201)


class Actions(BaseView):
    def post(self, request, **kwargs):
        space, app = self.context()
        services.apply_action(space, app, validated(ActionInput, request.data))
        # Physical cleanup is bounded by the maintenance process, not this request.
        return Response({"ok": True})


class UploadList(BaseView):
    def get(self, request, **kwargs):
        space, app = self.context()
        qs = DriveUpload.objects.filter(space=space, application=app).order_by("-updated_at")
        pager = PageNumberPagination()
        pager.page_size = 50
        return pager.get_paginated_response(UploadSerializer(pager.paginate_queryset(qs, request), many=True).data)

    def post(self, request, **kwargs):
        space, app = self.context()
        upload = services.create_upload(space, app, validated(UploadInput, request.data))
        return Response(UploadSerializer(upload).data, status=201)


class UploadDetail(BaseView):
    def get(self, request, pk, **kwargs):
        space, app = self.context()
        upload = get_object_or_404(DriveUpload, space=space, application=app, pk=pk)
        data = UploadSerializer(upload).data
        data["chunks"] = list(upload.chunks.order_by("offset").values("offset", "size", "sha256"))
        return Response(data)

    def delete(self, request, pk, **kwargs):
        space, app = self.context()
        return Response(UploadSerializer(services.cancel_upload(space, app, pk)).data)


class ChunkParser(BaseParser):
    media_type = "application/octet-stream"

    def parse(self, stream, media_type=None, parser_context=None):
        content = stream.read(settings.MY_DRIVE_CHUNK_BYTES + 1)
        if len(content) > settings.MY_DRIVE_CHUNK_BYTES:
            raise ValidationError("分片超过大小上限。")
        return content


class DriveChunkThrottle(UserRateThrottle):
    scope = "drive-chunks"
    rate = "2400/min"


class UploadChunk(BaseView):
    parser_classes = [ChunkParser]
    throttle_classes = [DriveChunkThrottle]

    def put(self, request, pk, **kwargs):
        space, app = self.context()
        offset = request.headers.get("X-Chunk-Offset", "")
        digest = request.headers.get("X-Chunk-SHA256", "")
        if not re.fullmatch(r"[0-9]{1,20}", offset) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValidationError("分片偏移或校验值无效。")
        upload = services.write_chunk(space, app, pk, int(offset), digest, request.data)
        return Response(UploadSerializer(upload).data)


class UploadComplete(BaseView):
    def post(self, request, pk, **kwargs):
        space, app = self.context()
        return Response(UploadSerializer(services.complete_upload(space, app, pk)).data)


class EntryAccess(BaseView):
    def post(self, request, pk, **kwargs):
        space, app = self.context()
        entry = get_object_or_404(services.entries(space, app), pk=pk, kind="file", trash_batch=None, purge_pending=False)
        mode = request.data.get("mode", "download")
        kind = preview_kind(entry)
        if mode not in {"preview", "download"} or (mode == "preview" and kind == "unsupported"):
            raise ValidationError("该格式不支持在线预览，请下载查看。")
        token = signing.dumps({"entry": str(entry.id), "user": request.user.pk,
            "organization": str(app.organization_id), "application": app.pk, "mode": mode}, salt=MEDIA_SALT)
        return Response({"token": token, "kind": kind, "expires_in": settings.MY_DRIVE_ACCESS_TTL_SECONDS})

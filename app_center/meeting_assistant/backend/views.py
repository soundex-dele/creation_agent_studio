import uuid
from pathlib import Path
from urllib.parse import urlsplit
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.enterprise.models import Membership
from modules.tenancy.permissions import HasPathOrganizationRole
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import DeploymentUnavailable, InvalidExecutionDefinition, IdempotencyKeyReused
from app_center.ideas_todos.backend.serializers import TodoSerializer
from app_center.documents.backend.serializers import DocumentSerializer
from app_center.documents.backend.content import plain_text
from .access import application_for, recording_for
from .models import Recording, DocumentExport
from .serializers import UploadSerializer, RecordingSerializer, RecordingSummarySerializer, MetadataSerializer, TranscriptSerializer, ActionSerializer, action_revision
from .services import check_version, check_idle, start, cancel, delete_record, Conflict, document_content, evidence_text
from .storage import store_upload, object_path


def key_for(request):
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 160:
        raise ValidationError("请提供有效的 Idempotency-Key。")
    return key


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def record(self, lock=False):
        return recording_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"], self.kwargs["pk"], lock=lock)

    def serialize(self, record):
        return RecordingSerializer(record).data


class RecordList(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        queryset = Recording.objects.filter(organization_id=app.organization_id, application=app, owner=request.user).select_related("active_run").defer("segments", "analysis")
        search = request.query_params.get("search", "").strip()[:200]
        if search:
            queryset = queryset.filter(title__icontains=search)
        kind = request.query_params.get("kind")
        if kind:
            if kind not in ("meeting", "interview"):
                raise ValidationError("记录类型无效。")
            queryset = queryset.filter(kind=kind)
        pagination = PageNumberPagination()
        pagination.page_size = 20
        rows = pagination.paginate_queryset(queryset, request)
        return pagination.get_paginated_response(RecordingSummarySerializer(rows, many=True).data)

    def post(self, request, **kwargs):
        app = self.application()
        values = UploadSerializer(data=request.data)
        values.is_valid(raise_exception=True)
        fields = dict(values.validated_data)
        upload = fields.pop("audio")
        record_id = uuid.uuid4()
        key = f"{app.organization_id}/{request.user.id}/{record_id}{Path(upload.name).suffix.lower()}"
        duration = store_upload(upload, key)
        try:
            with transaction.atomic():
                record = Recording.objects.create(id=record_id, organization=app.organization, application=app,
                    owner=request.user, filename=Path(upload.name).name[:255], object_key=key,
                    duration=duration, size=upload.size, **fields)
                try:
                    with transaction.atomic():
                        start(record, request.user, f"meeting-upload:{record_id}")
                except (DeploymentUnavailable, InvalidExecutionDefinition):
                    record.active_run = None
                    record.stage = "failed"
                    record.error = "录音已保存，但执行服务不可用。配置应用部署后可重试。"
                    record.save(update_fields=["active_run", "stage", "error"])
        except Exception:
            object_path(key).unlink(missing_ok=True)
            raise
        return Response(self.serialize(record), status=201)


class RecordDetail(BaseView):
    def get(self, request, **kwargs):
        return Response(self.serialize(self.record()))

    @transaction.atomic
    def patch(self, request, **kwargs):
        record = self.record(lock=True)
        check_version(record, request.data.get("version"))
        check_idle(record)
        serializer = MetadataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changed_context = any(getattr(record, k) != v for k, v in serializer.validated_data.items() if k != "title")
        for key, value in serializer.validated_data.items():
            setattr(record, key, value)
        if changed_context:
            record.version += 1
        record.save()
        return Response(self.serialize(record))

    @transaction.atomic
    def delete(self, request, **kwargs):
        delete_record(self.record(lock=True), request.user)
        return Response(status=204)


class Transcript(BaseView):
    @transaction.atomic
    def patch(self, request, **kwargs):
        record = self.record(lock=True)
        values = TranscriptSerializer(data=request.data)
        values.is_valid(raise_exception=True)
        check_version(record, values.validated_data["version"])
        check_idle(record)
        edits = values.validated_data["segments"]
        ids = [item["id"] for item in edits]
        if len(set(ids)) != len(ids) or set(ids) - {s["id"] for s in record.segments}:
            raise ValidationError("逐字稿分段无效，请刷新后重试。")
        by_id = {item["id"]: item["text"] for item in edits}
        changed = False
        for segment in record.segments:
            if segment["id"] in by_id and segment["text"] != by_id[segment["id"]]:
                segment["text"] = by_id[segment["id"]]
                changed = True
        if changed:
            record.version += 1
            record.save(update_fields=["segments", "version", "updated_at"])
        return Response(self.serialize(record))


class RecordRuns(BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        record = self.record(lock=True)
        check_version(record, request.data.get("version"))
        try:
            run = start(record, request.user, key_for(request), request.data.get("operation", "process"))
        except (DeploymentUnavailable, InvalidExecutionDefinition, IdempotencyKeyReused) as exc:
            raise Conflict(str(exc))
        return Response(RunSerializer(run).data, status=202)


class CancelRun(BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        record = self.record(lock=True)
        cancel(record, request.user)
        record.refresh_from_db()
        return Response(self.serialize(record))


class ActionDetail(BaseView):
    @transaction.atomic
    def patch(self, request, **kwargs):
        record = self.record(lock=True)
        check_idle(record)
        check_version(record, request.data.get("version"))
        if record.analysis_version != record.version:
            raise Conflict("分析结果已过期，请先重新分析。")
        action = get_object_or_404(record.actions, pk=kwargs["action_id"], analysis_version=record.analysis_version)
        if request.data.get("revision") != action_revision(action):
            raise Conflict("候选行动项已被修改，请刷新后核对。")
        if action.confirmed_at:
            raise Conflict("行动项已加入待办，请在待办应用中修改。")
        serializer = ActionSerializer(action, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ConfirmActions(BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        record = self.record(lock=True)
        check_version(record, request.data.get("version"))
        check_idle(record)
        if record.analysis_version != record.version:
            raise Conflict("分析结果已过期，请先重新分析。")
        if request.data.get("confirmed") is not True:
            raise ValidationError("请明确确认后再加入待办。")
        ids_field = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=200)
        ids = set(ids_field.run_validation(request.data.get("action_ids")))
        items = list(record.actions.filter(pk__in=ids, analysis_version=record.analysis_version))
        if len(items) != len(ids):
            raise ValidationError("行动项不存在或已更新。")
        revisions = request.data.get("action_versions")
        if not isinstance(revisions, dict) or any(revisions.get(str(item.pk)) != action_revision(item) for item in items):
            raise Conflict("候选行动项已被修改，请刷新后重新核对并确认。")
        target = application_for(request.user, record.organization_id, slug="ideas-todos")
        for item in items:
            if item.confirmed_at:
                continue
            serializer = TodoSerializer(data={"title": item.title, "description": item.description +
                f"\n\n来源：{record.title}（{record.recorded_on}）[{evidence_text(record, item.segment_ids)}]",
                "priority": item.priority, "due_date": item.due_date})
            serializer.is_valid(raise_exception=True)
            item.todo = serializer.save(organization_id=record.organization_id, application=target, owner=request.user)
            item.confirmed_at = timezone.now()
            item.save(update_fields=["todo", "confirmed_at"])
        return Response({"application_id": target.pk, "actions": ActionSerializer(items, many=True).data})


class ExportDocument(BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        record = self.record(lock=True)
        kind = request.data.get("kind")
        if kind not in ("transcript", "minutes", "materials") or (kind == "materials" and record.kind != "interview"):
            raise ValidationError("请选择有效的文档类型。")
        check_version(record, request.data.get("version"))
        if not record.segments or (kind != "transcript" and record.analysis_version != record.version):
            raise Conflict("请先完成转录及对应版本的分析。")
        key = key_for(request)
        target = application_for(request.user, record.organization_id, slug="documents")
        prior = record.exports.filter(key=key).first()
        if prior:
            if prior.kind != kind or prior.version != record.version:
                raise Conflict("该请求标识已用于其他导出。")
            if not prior.document_id:
                raise Conflict("此前导出的文档已删除，请重新发起导出。")
            return Response({"document_id": str(prior.document_id), "application_id": target.pk})
        source_path = f"/applications/{record.application_id}/meeting-assistant?record={record.pk}"
        source_url = request.build_absolute_uri(source_path)
        # The browser's Origin survives the Vite API proxy, whose Host points
        # to Django rather than the SPA. The document serializer still checks
        # the resulting link; no request-controlled path is accepted here.
        origin = urlsplit(request.headers.get("Origin", ""))
        if origin.scheme in ("http", "https") and origin.netloc and not origin.username and origin.path in ("", "/"):
            source_url = f"{origin.scheme}://{origin.netloc}{source_path}"
        body = document_content(record, kind, source_url)
        serializer = DocumentSerializer(data={"title": (record.title + {"transcript": " · 逐字稿", "minutes": " · 会议纪要", "materials": " · 访谈素材"}[kind])[:200], "content": body}, context={"request": request})
        serializer.is_valid(raise_exception=True)
        document = serializer.save(organization_id=record.organization_id, application=target,
                                   owner=request.user, plain_text=plain_text(body))
        DocumentExport.objects.create(organization_id=record.organization_id, recording=record,
            key=key, kind=kind, version=record.version, document=document)
        return Response({"document_id": str(document.pk), "application_id": target.pk}, status=201)

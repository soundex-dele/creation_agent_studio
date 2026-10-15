import uuid

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.enterprise.models import Membership
from modules.execution.api.serializers import RunSerializer, RunArtifactSerializer
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from modules.execution.application.start_runs import start_application_run
from modules.execution.infrastructure.artifacts import get_artifact_storage, ArtifactObjectUnavailable
from modules.tenancy.permissions import HasPathOrganizationRole
from .access import application_for, drawings_for, reference_for, source_for
from .images import inspect_image, MAX_IMAGE_BYTES
from .models import DrawingReference
from .serializers import GenerateSerializer


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def serialize(self, run):
        data = RunSerializer(run, context={"request": self.request}).data
        data["artifacts"] = RunArtifactSerializer(run.artifacts.filter(kind="drawing"), many=True).data
        return data


class ReferencesView(BaseView):
    def post(self, request, **kwargs):
        application = self.application()
        upload = request.FILES.get("file")
        if upload is None or upload.size > MAX_IMAGE_BYTES:
            raise ValidationError({"file": "请选择不超过 20 MB 的 PNG、JPEG 或 WebP 图片。"})
        content = upload.read(MAX_IMAGE_BYTES + 1)
        metadata = inspect_image(content)
        reference_id = uuid.uuid4()
        key = f"ai-drawing/{application.organization_id}/{request.user.id}/references/{reference_id}"
        storage = get_artifact_storage()
        storage.put(key, content)
        try:
            reference = DrawingReference.objects.create(id=reference_id, organization=application.organization,
                application=application, owner=request.user, object_key=key, size=len(content), **metadata)
        except Exception:
            storage.delete(key)
            raise
        return Response({"id": str(reference.id), "size": reference.size, **metadata}, status=201)


class ReferenceContentView(BaseView):
    def get(self, request, reference_id, **kwargs):
        reference = reference_for(request.user, self.application(), reference_id)
        try:
            handle = get_artifact_storage().open(reference.object_key)
        except ArtifactObjectUnavailable:
            raise Http404("参考图文件已不可用。") from None
        response = FileResponse(handle, content_type=reference.mime_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class GenerationsView(BaseView):
    def get(self, request, **kwargs):
        runs = drawings_for(request.user, self.application()).order_by("-created_at", "-id")
        pagination = PageNumberPagination()
        pagination.page_size = 20
        page = pagination.paginate_queryset(runs, request)
        return pagination.get_paginated_response([self.serialize(run) for run in page])

    def post(self, request, **kwargs):
        application = self.application()
        serializer = GenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if values.get("reference_id"):
            reference_for(request.user, application, values["reference_id"])
        if values.get("source_artifact_id"):
            source_for(request.user, application, values["source_artifact_id"])
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key or len(key) > 160:
            raise ValidationError("必须提供有效的 Idempotency-Key。")
        try:
            run, replay = start_application_run(organization_id=application.organization_id,
                application_id=application.id, actor=request.user, input_data=values,
                priority=0, idempotency_key=key)
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(self.serialize(run), status=200 if replay else 201)


class GenerationView(BaseView):
    def get(self, request, run_id, **kwargs):
        run = get_object_or_404(drawings_for(request.user, self.application()), pk=run_id)
        return Response(self.serialize(run))

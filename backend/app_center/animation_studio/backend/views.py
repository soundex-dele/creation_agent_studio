import uuid
from pathlib import Path

from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.enterprise.models import Membership
from modules.execution.api.serializers import RunSerializer, RunArtifactSerializer
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from modules.execution.infrastructure.artifacts import get_artifact_storage
from modules.tenancy.permissions import HasPathOrganizationRole
from .access import application_for, runs_for, generation_for, assets_for
from .serializers import AnimationInputSerializer
from .models import AnimationAsset
from .media import inspect_upload


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def serialize_run(self, run):
        data = RunSerializer(run, context={"request": self.request}).data
        data["artifacts"] = RunArtifactSerializer(run.artifacts.all(), many=True).data
        return data

    def serialize(self, run, application):
        data = self.serialize_run(run)
        data["exports"] = [self.serialize_run(item) for item in runs_for(self.request.user, application).filter(
            input__action="export", input__source_run_id=str(run.id)).order_by("-created_at", "-id")]
        return data

    def start(self, application, values):
        key = (self.request.headers.get("Idempotency-Key") or "").strip()
        if not key or len(key) > 160:
            raise ValidationError("必须提供有效的 Idempotency-Key。")
        try:
            run, replay = start_application_run(organization_id=application.organization_id,
                application_id=application.id, actor=self.request.user, input_data=values,
                priority=0, idempotency_key=key)
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(self.serialize(run, application) if values["action"] == "generate" else self.serialize_run(run),
                        status=200 if replay else 201)


class AssetsView(BaseView):
    def post(self, request, **kwargs):
        application = self.application()
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError("请选择素材文件。")
        content, metadata = inspect_upload(upload)
        asset_id = uuid.uuid4()
        key = f"animation-studio/{application.organization_id}/{request.user.id}/assets/{asset_id}"
        storage = get_artifact_storage()
        storage.put(key, content)
        try:
            asset = AnimationAsset.objects.create(id=asset_id, organization=application.organization,
                application=application, owner=request.user, name=Path(upload.name).name[:200],
                object_key=key, size=len(content), **metadata)
        except Exception:
            storage.delete(key)
            raise
        return Response({"id": str(asset.id), "name": asset.name, "size": asset.size, **metadata}, status=201)


class GenerationsView(BaseView):
    def get(self, request, **kwargs):
        application = self.application()
        runs = runs_for(request.user, application).filter(input__action="generate").order_by("-created_at", "-id")
        pagination = PageNumberPagination()
        pagination.page_size = 20
        page = pagination.paginate_queryset(runs, request)
        return pagination.get_paginated_response([self.serialize(run, application) for run in page])

    def post(self, request, **kwargs):
        application = self.application()
        serializer = AnimationInputSerializer(data={**request.data, "action": "generate"})
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        assets_for(request.user, application, values["asset_ids"])
        if values.get("source_run_id"):
            generation_for(request.user, application, values["source_run_id"], ready=True)
        return self.start(application, values)


class GenerationView(BaseView):
    def get(self, request, run_id, **kwargs):
        application = self.application()
        return Response(self.serialize(generation_for(request.user, application, run_id), application))


class ExportsView(BaseView):
    def post(self, request, run_id, **kwargs):
        application = self.application()
        source = generation_for(request.user, application, run_id, ready=True)
        return self.start(application, {"action": "export", "source_run_id": str(source.id)})

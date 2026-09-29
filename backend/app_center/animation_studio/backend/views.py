import uuid
from pathlib import Path
from django.db import transaction

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
    def get(self, request, **kwargs):
        app = self.application()
        items = AnimationAsset.objects.for_organization(app.organization_id).filter(application=app, owner=request.user,
            archived=request.query_params.get("archived") == "1", name__icontains=request.query_params.get("q", "")[:200]).order_by("-created_at")
        return Response({"results": [{"id": str(i.id), "name": i.name, "category": i.category, "archived": i.archived,
            "mime_type": i.mime_type, "size": i.size, "duration": i.duration} for i in items[:500]]})

    def post(self, request, **kwargs):
        application = self.application()
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError("请选择素材文件。")
        content, metadata = inspect_upload(upload, allow_short=True)
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
        runs = runs_for(request.user, application).filter(input__action="generate", animation_version__deleted_at__isnull=True).order_by("-created_at", "-id")
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
        run = generation_for(request.user, application, run_id)
        data = self.serialize(run, application)
        from .models import AnimationVersion
        linked = AnimationVersion.objects.filter(run=run).first()
        data["project_id"] = str(linked.project_id) if linked else None
        return Response(data)


class ExportsView(BaseView):
    @transaction.atomic
    def post(self, request, run_id, **kwargs):
        application = self.application()
        source = generation_for(request.user, application, run_id, ready=True, lock=True)
        from .studio_validation import export_options
        values = {"action": "export", "source_run_id": str(source.id)}
        if request.data:
            values["export_options"] = export_options(request.data)
        return self.start(application, values)

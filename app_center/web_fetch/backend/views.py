from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.platform_api.identity import Membership
from modules.platform_api.tenancy import HasPathOrganizationRole
from modules.platform_api.execution import (
    RunSerializer, RunArtifactSerializer, start_application_run,
    DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition,
)
from .access import application_for, runs_for
from .serializers import FetchSerializer


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def serialize(self, run):
        data = RunSerializer(run, context={"request": self.request}).data
        data["artifacts"] = RunArtifactSerializer(run.artifacts.filter(kind__in=["web-markdown", "web-document"]), many=True).data
        return data


class RunsView(BaseView):
    def get(self, request, **kwargs):
        queryset = runs_for(request.user, self.application()).prefetch_related("artifacts").order_by("-created_at", "-id")
        pagination = PageNumberPagination()
        pagination.page_size = 20
        page = pagination.paginate_queryset(queryset, request)
        return pagination.get_paginated_response([self.serialize(run) for run in page])

    def post(self, request, **kwargs):
        application = self.application()
        serializer = FetchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key or len(key) > 160:
            raise ValidationError("必须提供有效的 Idempotency-Key。")
        try:
            run, replay = start_application_run(organization_id=application.organization_id,
                application_id=application.id, actor=request.user, input_data=serializer.validated_data,
                priority=0, idempotency_key=key)
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(self.serialize(run), status=200 if replay else 201)


class RunView(BaseView):
    def get(self, request, run_id, **kwargs):
        return Response(self.serialize(get_object_or_404(runs_for(request.user, self.application()), pk=run_id)))

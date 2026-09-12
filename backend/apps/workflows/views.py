"""Workflow authoring with durable Run execution only."""
from uuid import uuid4

from django.conf import settings
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.enterprise.models import Membership
from apps.enterprise.permissions import OrganizationRolePermission, resolve_organization
from modules.catalog.models import ApplicationDeployment, DeploymentEnvironment
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.start_runs import start_workflow_run

from .models import Workflow
from .serializers import (
    WorkflowDetailSerializer,
    WorkflowListSerializer,
    WorkflowWriteSerializer,
)


class WorkflowViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]

    def get_queryset(self):
        organization = resolve_organization(self.request)
        return Workflow.objects.filter(organization=organization).filter(
            Q(owner=self.request.user) | Q(is_public=True)
        ).annotate(step_count=Count("steps")).prefetch_related(
            "steps__application__chat_profile",
            "steps__application__agent_bindings__agent",
            "steps__application__skill_bindings__skill",
            "steps__application__guided_prompts__questions__options",
        )

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkflowWriteSerializer
        if self.action == "list":
            return WorkflowListSerializer
        return WorkflowDetailSerializer

    def perform_create(self, serializer):
        serializer.save(
            owner=self.request.user,
            organization=resolve_organization(self.request),
        )

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.id:
            raise PermissionDenied("只有工作流所有者可以编辑。")
        serializer.save()

    def perform_destroy(self, instance):
        membership = self.request.organization_membership
        if (
            instance.owner_id != self.request.user.id
            and membership.role not in (Membership.Role.OWNER, Membership.Role.ADMIN)
        ):
            raise PermissionDenied("无权删除该工作流。")
        instance.delete()

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        workflow = self.get_object()
        steps = list(
            workflow.steps.select_related("application").order_by("order", "id")
        )
        if not steps:
            return Response({"detail": "工作流至少需要一个应用。"}, status=400)
        snapshots = []
        for step in steps:
            deployment = ApplicationDeployment.objects.for_organization(
                workflow.organization_id
            ).select_related("revision").filter(
                application=step.application,
                environment=DeploymentEnvironment.PRODUCTION,
            ).first()
            if deployment is None:
                return Response(
                    {"detail": f"步骤“{step.name or step.application.name}”没有 production 部署。"},
                    status=409,
                )
            content = deployment.revision.content
            kind = content.get("executor_kind")
            key = content.get("executor_key")
            if key not in settings.EXECUTION_CHILD_ADAPTERS.get(kind, {}):
                return Response(
                    {"detail": f"步骤执行器未注册：{kind}/{key}"},
                    status=422,
                )
            snapshots.append({
                "id": str(step.id),
                "key": step.key,
                "name": step.name or step.application.name,
                "depends_on": step.depends_on,
                "condition": step.condition,
                "max_attempts": step.max_attempts,
                "application_id": step.application_id,
                "application_revision_id": str(deployment.revision_id),
                "executor_kind": kind,
                "executor_key": key,
                "content": content,
                "effective_config": {
                    **dict(content.get("default_config") or {}),
                    **dict(deployment.config_override or {}),
                    **dict(step.config or {}),
                },
            })
        run, _ = start_workflow_run(
            organization=workflow.organization,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            steps=snapshots,
            actor=request.user,
            input_data=request.data.get("input") or {},
            priority=int(request.data.get("priority") or 0),
            idempotency_key=request.headers.get("Idempotency-Key") or str(uuid4()),
        )
        body = RunSerializer(run).data
        body["organization_id"] = str(workflow.organization_id)
        return Response(body, status=status.HTTP_202_ACCEPTED)

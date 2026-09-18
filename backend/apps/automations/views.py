import uuid

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.enterprise.models import Membership
from apps.workflows.models import Workflow
from modules.catalog.models import ApplicationDeployment
from modules.tenancy.database import tenant_database_context
from modules.tenancy.permissions import (
    HasPathOrganization,
    HasPathOrganizationRole,
    ROLE_LEVEL,
)
from core.resource_access import accessible_resources

from .models import Automation, AutomationInvocation
from .serializers import (
    AutomationInvocationSerializer,
    AutomationSerializer,
    AutomationTargetSerializer,
    AutomationWriteSerializer,
    SchedulePreviewSerializer,
    SchedulePreviewResponseSerializer,
)
from .services import (
    AutomationValidationError,
    IdempotencyConflict,
    disable_automation,
    dispatch_automation,
    enable_automation,
    record_audit,
    rotate_secret,
    verify_secret,
)
from .throttles import AutomationWebhookThrottle


def _queryset(organization_id):
    return Automation.objects.filter(
        organization_id=organization_id
    ).exclude(status=Automation.Status.ARCHIVED).select_related(
        "application", "workflow", "created_by"
    )


def _require_role(request, role):
    if request.user.is_superuser:
        return True
    membership = getattr(request, "organization_membership", None)
    if membership is None and getattr(request, "organization", None) is not None:
        membership = Membership.objects.filter(
            organization=request.organization,
            user=request.user,
            is_active=True,
        ).first()
        request.organization_membership = membership
    return bool(
        membership
        and ROLE_LEVEL.get(membership.role, 0) >= ROLE_LEVEL.get(role, 100)
    )


class AutomationListCreateView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    @swagger_auto_schema(responses={200: AutomationSerializer(many=True)})
    def get(self, request, organization_id):
        queryset = _queryset(organization_id)
        trigger_type = request.query_params.get("trigger_type")
        automation_status = request.query_params.get("status")
        target_type = request.query_params.get("target_type")
        if trigger_type:
            queryset = queryset.filter(trigger_type=trigger_type)
        if automation_status:
            queryset = queryset.filter(status=automation_status)
        if target_type:
            queryset = queryset.filter(target_type=target_type)
        return Response(AutomationSerializer(
            queryset[:200], many=True, context={"request": request}
        ).data)

    @swagger_auto_schema(
        request_body=AutomationWriteSerializer,
        responses={201: AutomationSerializer},
    )
    def post(self, request, organization_id):
        serializer = AutomationWriteSerializer(
            data=request.data,
            context={"request": request, "organization": request.organization},
        )
        serializer.is_valid(raise_exception=True)
        automation = serializer.save(
            organization=request.organization,
            created_by=request.user,
        )
        secret = ""
        if automation.trigger_type == Automation.TriggerType.WEBHOOK:
            secret = rotate_secret(automation)
        record_audit(automation, request.user, "created")
        body = AutomationSerializer(automation, context={"request": request}).data
        if secret:
            body["webhook_secret"] = secret
        return Response(body, status=status.HTTP_201_CREATED)


class AutomationDetailView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get_object(self, organization_id, automation_id):
        return _queryset(organization_id).filter(pk=automation_id).first()

    @swagger_auto_schema(responses={200: AutomationSerializer})
    def get(self, request, organization_id, automation_id):
        automation = self.get_object(organization_id, automation_id)
        if automation is None:
            return Response({"detail": "自动化不存在。"}, status=404)
        return Response(AutomationSerializer(
            automation, context={"request": request}
        ).data)

    @swagger_auto_schema(
        request_body=AutomationWriteSerializer,
        responses={200: AutomationSerializer},
    )
    def patch(self, request, organization_id, automation_id):
        automation = self.get_object(organization_id, automation_id)
        if automation is None:
            return Response({"detail": "自动化不存在。"}, status=404)
        serializer = AutomationWriteSerializer(
            automation,
            data=request.data,
            partial=True,
            context={"request": request, "organization": request.organization},
        )
        serializer.is_valid(raise_exception=True)
        automation = serializer.save()
        record_audit(automation, request.user, "updated")
        return Response(AutomationSerializer(
            automation, context={"request": request}
        ).data)

    @swagger_auto_schema(responses={204: "Archived"})
    def delete(self, request, organization_id, automation_id):
        if not _require_role(request, Membership.Role.ADMIN):
            return Response({"detail": "需要管理员权限。"}, status=403)
        automation = self.get_object(organization_id, automation_id)
        if automation is None:
            return Response({"detail": "自动化不存在。"}, status=404)
        automation.status = Automation.Status.ARCHIVED
        automation.is_active = False
        automation.next_run_at = None
        automation.archived_at = timezone.now()
        automation.save(update_fields=(
            "status", "is_active", "next_run_at", "archived_at", "updated_at",
        ))
        record_audit(automation, request.user, "archived")
        return Response(status=204)


class AutomationActionView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganization)
    action_name = ""

    @swagger_auto_schema(
        request_body=openapi.Schema(type=openapi.TYPE_OBJECT),
        responses={200: AutomationSerializer, 202: AutomationInvocationSerializer},
    )
    def post(self, request, organization_id, automation_id, action_name=None):
        action_name = action_name or self.action_name
        automation = _queryset(organization_id).filter(pk=automation_id).first()
        if automation is None:
            return Response({"detail": "自动化不存在。"}, status=404)
        admin_actions = {"rotate-secret", "take-over"}
        required = Membership.Role.ADMIN if action_name in admin_actions else Membership.Role.OPERATOR
        if not _require_role(request, required):
            return Response({"detail": "当前角色无权执行此操作。"}, status=403)

        try:
            if action_name == "enable":
                enable_automation(automation)
                record_audit(automation, request.user, "enabled")
            elif action_name == "disable":
                disable_automation(automation)
                record_audit(automation, request.user, "disabled")
            elif action_name == "run":
                payload = request.data if isinstance(request.data, dict) else {}
                invocation, replayed = dispatch_automation(
                    automation,
                    source=AutomationInvocation.Source.MANUAL,
                    payload=payload,
                    dedup_key=(request.headers.get("Idempotency-Key") or str(uuid.uuid4())),
                )
                record_audit(automation, request.user, "triggered", {
                    "invocation_id": str(invocation.id), "replayed": replayed,
                })
                response_status = (
                    429 if invocation.outcome == AutomationInvocation.Outcome.SKIPPED_CAPACITY
                    else 422 if invocation.outcome == AutomationInvocation.Outcome.FAILED
                    else 202
                )
                return Response(
                    AutomationInvocationSerializer(invocation).data,
                    status=response_status,
                )
            elif action_name == "rotate-secret":
                if automation.trigger_type != Automation.TriggerType.WEBHOOK:
                    return Response({"detail": "只有 Webhook 自动化拥有密钥。"}, status=409)
                secret = rotate_secret(automation)
                record_audit(automation, request.user, "secret_rotated")
                body = AutomationSerializer(automation, context={"request": request}).data
                body["webhook_secret"] = secret
                return Response(body)
            elif action_name == "take-over":
                automation.created_by = request.user
                automation.status = Automation.Status.PAUSED
                automation.is_active = False
                automation.blocked_reason = ""
                automation.next_run_at = None
                automation.save(update_fields=(
                    "created_by", "status", "is_active", "blocked_reason",
                    "next_run_at", "updated_at",
                ))
                record_audit(automation, request.user, "taken_over")
            else:
                return Response({"detail": "不支持的操作。"}, status=404)
        except AutomationValidationError as exc:
            return Response({"detail": str(exc)}, status=409)
        except IdempotencyConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(AutomationSerializer(
            automation, context={"request": request}
        ).data)


class AutomationInvocationListView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    @swagger_auto_schema(responses={200: AutomationInvocationSerializer(many=True)})
    def get(self, request, organization_id, automation_id):
        automation = _queryset(organization_id).filter(pk=automation_id).first()
        if automation is None:
            return Response({"detail": "自动化不存在。"}, status=404)
        invocations = automation.invocations.select_related("run")[:100]
        return Response(AutomationInvocationSerializer(invocations, many=True).data)


class AutomationEnableView(AutomationActionView):
    action_name = "enable"


class AutomationDisableView(AutomationActionView):
    action_name = "disable"


class AutomationRunView(AutomationActionView):
    action_name = "run"


class AutomationRotateSecretView(AutomationActionView):
    action_name = "rotate-secret"


class AutomationTakeOverView(AutomationActionView):
    action_name = "take-over"


class AutomationTargetListView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    @swagger_auto_schema(
        manual_parameters=[openapi.Parameter(
            "type", openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING,
            enum=["application", "workflow"],
        )],
        responses={200: AutomationTargetSerializer(many=True)},
    )
    def get(self, request, organization_id):
        target_type = request.query_params.get("type")
        if target_type == Automation.TargetType.APPLICATION:
            application_ids = ApplicationDeployment.objects.for_organization(
                organization_id
            ).values_list(
                "application_id", flat=True
            )
            targets = accessible_resources(Application.objects.filter(
                Q(organization_id=organization_id) | Q(organization__isnull=True),
                id__in=application_ids,
                is_active=True,
            ), request.user, operation="run").order_by("name")
            return Response([{
                "type": "application", "id": str(item.id), "name": item.name,
                "description": item.description,
            } for item in targets])
        if target_type == Automation.TargetType.WORKFLOW:
            targets = Workflow.objects.filter(
                organization_id=organization_id,
                execution_mode=Workflow.ExecutionMode.AUTOMATIC,
            ).filter(Q(owner=request.user) | Q(is_public=True)).order_by("name")
            return Response([{
                "type": "workflow", "id": str(item.id), "name": item.name,
                "description": item.description,
            } for item in targets])
        return Response({"detail": "type 必须是 application 或 workflow。"}, status=400)


class SchedulePreviewView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    @swagger_auto_schema(
        request_body=SchedulePreviewSerializer,
        responses={200: SchedulePreviewResponseSerializer},
    )
    def post(self, request, organization_id):
        serializer = SchedulePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({
            "next_runs": [value.isoformat() for value in serializer.validated_data["next_runs"]]
        })


class AutomationWebhookView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AutomationWebhookThrottle,)
    max_content_length = 1024 * 1024

    @swagger_auto_schema(
        request_body=openapi.Schema(type=openapi.TYPE_OBJECT),
        responses={202: AutomationInvocationSerializer},
    )
    def post(self, request, public_id):
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        if content_length > self.max_content_length:
            return Response({"detail": "Webhook 请求体不能超过 1 MiB。"}, status=413)
        automation = Automation.objects.select_related(
            "organization", "created_by", "application", "workflow"
        ).filter(public_id=public_id).first()
        if automation is None:
            return Response({"detail": "Webhook 不存在。"}, status=404)
        authorization = request.headers.get("Authorization", "")
        secret = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        if not verify_secret(automation, secret):
            return Response({"detail": "Webhook 密钥无效。"}, status=401)
        if (
            automation.status != Automation.Status.ACTIVE
            or automation.trigger_type != Automation.TriggerType.WEBHOOK
        ):
            return Response({"detail": "Webhook 自动化未启用。"}, status=409)
        if not isinstance(request.data, dict):
            return Response({"detail": "Webhook 载荷必须是 JSON 对象。"}, status=400)
        dedup_key = (request.headers.get("Idempotency-Key") or str(uuid.uuid4())).strip()
        if not dedup_key or len(dedup_key) > 160:
            return Response({"detail": "Idempotency-Key 长度必须为 1 到 160。"}, status=400)
        try:
            with tenant_database_context(automation.organization_id):
                invocation, replayed = dispatch_automation(
                    automation,
                    source=AutomationInvocation.Source.WEBHOOK,
                    payload=request.data,
                    dedup_key=f"webhook:{dedup_key}",
                )
        except IdempotencyConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        body = AutomationInvocationSerializer(invocation).data
        body["replayed"] = replayed
        response_status = (
            429 if invocation.outcome == AutomationInvocation.Outcome.SKIPPED_CAPACITY
            else 422 if invocation.outcome == AutomationInvocation.Outcome.FAILED
            else 202
        )
        return Response(body, status=response_status)

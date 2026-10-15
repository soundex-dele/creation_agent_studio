from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import Agent
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole
from .models import Binding
from .protocol import seal, unseal
from .serializers import BindingSerializer, ConfigurationSerializer, VerifySerializer, AgentOptionSerializer, TaskSerializer
from .services import configure, start_login, unbind, check_access


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self, request, application_id):
        return get_object_or_404(accessible_resources(
            Application.objects.filter(organization=request.organization, slug="wechat-assistant", is_active=True),
            request.user, operation="run",
        ), pk=application_id)

    def binding(self, request, application_id, *, create=False):
        app = self.application(request, application_id)
        query = Binding.objects.filter(organization=request.organization, user=request.user, application=app)
        if create:
            return Binding.objects.get_or_create(organization=request.organization, user=request.user, application=app)[0]
        return get_object_or_404(query)


class StatusView(BaseView):
    @swagger_auto_schema(responses={200: BindingSerializer(), 204: "尚未配置"})
    def get(self, request, application_id, **kwargs):
        app = self.application(request, application_id)
        binding = Binding.objects.filter(organization=request.organization, user=request.user, application=app).first()
        return Response(BindingSerializer(binding).data) if binding else Response(status=204)

    @swagger_auto_schema(request_body=ConfigurationSerializer, responses={200: BindingSerializer})
    def put(self, request, application_id, **kwargs):
        serializer = ConfigurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            binding = configure(self.binding(request, application_id, create=True), serializer.validated_data["agent_id"])
        return Response(BindingSerializer(binding).data)


class AgentsView(BaseView):
    @swagger_auto_schema(responses={200: AgentOptionSerializer(many=True)})
    def get(self, request, application_id, **kwargs):
        self.application(request, application_id)
        agents = accessible_resources(Agent.objects.filter(Q(organization=request.organization) | Q(organization__isnull=True), is_active=True), request.user, operation="run")
        return Response(AgentOptionSerializer(agents.order_by("name"), many=True).data)


class LoginView(BaseView):
    @swagger_auto_schema(responses={202: BindingSerializer})
    def post(self, request, application_id, **kwargs):
        binding = start_login(self.binding(request, application_id))
        return Response(BindingSerializer(binding).data, status=202)


class VerifyView(BaseView):
    @swagger_auto_schema(request_body=VerifySerializer, responses={202: BindingSerializer})
    def post(self, request, application_id, **kwargs):
        serializer = VerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            binding = Binding.objects.select_for_update().get(pk=self.binding(request, application_id).pk)
            if binding.status != "need_verifycode" or binding.login_id != serializer.validated_data["login_id"] or binding.login_expires_at <= timezone.now():
                raise ValidationError("验证码请求已过期，请重新扫码。")
            data = unseal(binding.login_data)
            data["verify_code"] = serializer.validated_data["code"]
            binding.login_data = seal(data)
            binding.next_poll_at = timezone.now()
            binding.save(update_fields=["login_data", "next_poll_at", "updated_at"])
        return Response(BindingSerializer(binding).data, status=202)


class ReconnectView(BaseView):
    @swagger_auto_schema(responses={200: BindingSerializer})
    def post(self, request, application_id, **kwargs):
        with transaction.atomic():
            binding = Binding.objects.select_for_update().get(pk=self.binding(request, application_id).pk)
            check_access(binding)
            if not binding.credentials or binding.status == "expired":
                raise ValidationError("请重新扫码登录。")
            binding.enabled = True
            binding.status = "connecting"
            binding.next_poll_at = timezone.now()
            binding.last_error = ""
            binding.save()
        return Response(BindingSerializer(binding).data)


class UnbindView(BaseView):
    @swagger_auto_schema(responses={200: BindingSerializer})
    def post(self, request, application_id, **kwargs):
        return Response(BindingSerializer(unbind(self.binding(request, application_id))).data)


class NewConversationView(BaseView):
    @swagger_auto_schema(responses={200: BindingSerializer})
    def post(self, request, application_id, **kwargs):
        return Response(BindingSerializer(configure(self.binding(request, application_id), reset=True)).data)


class TasksView(BaseView):
    @swagger_auto_schema(responses={200: TaskSerializer(many=True)})
    def get(self, request, application_id, **kwargs):
        binding = self.binding(request, application_id)
        return Response(TaskSerializer(binding.incoming.select_related("run").prefetch_related("replies").order_by("-created_at")[:30], many=True).data)

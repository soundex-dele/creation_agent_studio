"""Conversation resources backed exclusively by the durable Run plane."""
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.agents.models import Agent, AgentSkillBinding
from apps.applications.models import Application, ApplicationSkillBinding, Skill
from apps.enterprise.permissions import resolve_organization
from apps.projects.models import Project
from apps.projects.services.workspace_files import (
    WorkspaceFileError,
    list_conversation_workspace_files,
    read_conversation_workspace_file,
)
from apps.projects.services.workspace_paths import conversation_working_directory
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import (
    DeploymentUnavailable,
    InvalidExecutionDefinition,
)
from modules.execution.application.start_runs import start_agent_run
from modules.execution.models import Run

from .models import Conversation, ConversationSkillBinding, Message
from .serializers import (
    ConversationDetailSerializer,
    ConversationListSerializer,
    CreateConversationSerializer,
    SendMessageSerializer,
)


GENERAL_AGENT_SLUG = "general"


def resolve_agent(agent_id, organization):
    visible = Agent.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True, is_public=True),
        is_active=True,
    )
    if agent_id is not None:
        selected = visible.filter(pk=agent_id).first()
        if selected is not None:
            return selected
    return get_object_or_404(visible, slug=GENERAL_AGENT_SLUG)


class ConversationViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def get_conversation(self, request, pk):
        organization = resolve_organization(request)
        return get_object_or_404(
            Conversation.objects.filter(organization=organization),
            pk=pk,
            user=request.user,
        )

    @action(detail=False, methods=["get"], url_path="composer-options")
    def composer_options(self, request):
        organization = resolve_organization(request)
        skills = Skill.objects.filter(
            Q(organization=organization)
            | Q(visibility=Skill.Visibility.PUBLIC),
            is_active=True,
        ).order_by("name")
        return Response({
            "skills": [
                {"name": skill.slug, "description": skill.description}
                for skill in skills
            ]
        })

    def list(self, request):
        organization = resolve_organization(request)
        queryset = request.user.conversations.filter(organization=organization)
        application_id = request.query_params.get("application_id")
        project_id = request.query_params.get("project_id")
        if application_id:
            queryset = queryset.filter(application_id=application_id)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
            process_id = request.query_params.get("process_id")
            if process_id:
                queryset = queryset.filter(process_id=process_id)
        elif not application_id:
            queryset = queryset.filter(project__isnull=True)
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(title__icontains=search)
        return Response(ConversationListSerializer(queryset[:20], many=True).data)

    def create(self, request):
        serializer = CreateConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        organization = resolve_organization(request)
        application = None
        if data.get("application_id"):
            application = get_object_or_404(
                Application.objects.filter(
                    Q(organization=organization)
                    | Q(organization__isnull=True, is_public=True),
                    is_active=True,
                ),
                id=data["application_id"],
                kind=Application.Kind.CHAT,
            )
        requested_agent_id = data.get("agent_id")
        if application is not None:
            bindings = application.agent_bindings.select_related("agent")
            binding = (
                bindings.filter(agent_id=requested_agent_id).first()
                if requested_agent_id
                else bindings.filter(is_default=True).first()
            )
            if binding is None:
                return Response(
                    {"agent_id": "该智能体不属于当前聊天应用。"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            agent = binding.agent
        else:
            agent = resolve_agent(requested_agent_id, organization)

        project = None
        if data.get("project_id"):
            project = get_object_or_404(
                Project.objects.filter(organization=organization),
                id=data["project_id"],
                user=request.user,
            )
        requested_directory = data.get("working_directory", "")
        if requested_directory and (application or project):
            return Response(
                {"working_directory": "应用或项目对话必须使用其自己的工作目录。"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        skill_sources = {}
        for binding in AgentSkillBinding.objects.filter(
            agent=agent,
            mode__in=[AgentSkillBinding.Mode.REQUIRED, AgentSkillBinding.Mode.DEFAULT],
        ):
            source = (
                ConversationSkillBinding.Source.AGENT_REQUIRED
                if binding.mode == AgentSkillBinding.Mode.REQUIRED
                else ConversationSkillBinding.Source.AGENT_DEFAULT
            )
            skill_sources[binding.skill_id] = (source, binding.config)
        if application:
            for binding in ApplicationSkillBinding.objects.filter(
                application=application,
                mode__in=[
                    ApplicationSkillBinding.Mode.REQUIRED,
                    ApplicationSkillBinding.Mode.DEFAULT,
                ],
            ):
                source = (
                    ConversationSkillBinding.Source.APP_REQUIRED
                    if binding.mode == ApplicationSkillBinding.Mode.REQUIRED
                    else ConversationSkillBinding.Source.APP_DEFAULT
                )
                skill_sources[binding.skill_id] = (source, binding.config)

        with transaction.atomic():
            conversation = Conversation.objects.create(
                user=request.user,
                organization=organization,
                title=data.get("title", ""),
                agent=agent,
                application=application,
                project=project,
                process_id=data.get("process_id", "") or "",
                working_directory=requested_directory,
            )
            conversation_working_directory(conversation)
            ConversationSkillBinding.objects.bulk_create([
                ConversationSkillBinding(
                    conversation=conversation,
                    skill_id=skill_id,
                    source=source,
                    config=config,
                )
                for skill_id, (source, config) in skill_sources.items()
            ])
        return Response(
            ConversationListSerializer(conversation).data,
            status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, pk=None):
        return Response(
            ConversationDetailSerializer(self.get_conversation(request, pk)).data
        )

    @action(detail=True, methods=["get"], url_path="workspace-files")
    def workspace_files(self, request, pk=None):
        conversation = self.get_conversation(request, pk)
        try:
            relative_path = request.query_params.get("path")
            if relative_path is not None:
                return Response(read_conversation_workspace_file(conversation, relative_path))
            return Response(list_conversation_workspace_files(conversation))
        except WorkspaceFileError as exc:
            return Response({"detail": str(exc)}, status=400)
        except FileNotFoundError:
            return Response({"detail": "文件不存在或已被删除。"}, status=404)

    def _create_run(self, request, conversation, message, requested_agent_id=None):
        organization = conversation.organization
        agent = resolve_agent(requested_agent_id or conversation.agent_id, organization)
        if conversation.agent_id != agent.id:
            conversation.agent = agent
        if not conversation.title:
            conversation.title = message[:50]
        conversation.save(update_fields=["agent", "title", "updated_at"])
        Message.objects.create(
            conversation=conversation,
            role="user",
            content=message,
            metadata={"run_request_id": getattr(request, "request_id", "")},
        )
        history = list(
            conversation.messages.order_by("created_at", "id").values("role", "content")
        )[-100:]
        return start_agent_run(
            organization_id=organization.id,
            agent_id=agent.id,
            actor=request.user,
            environment="production",
            input_data={
                "message": message,
                "messages": history,
                "working_directory": conversation.working_directory,
            },
            idempotency_key=(
                request.headers.get("Idempotency-Key") or str(uuid4())
            ),
            source_type="conversation",
            source_id=conversation.id,
        )

    @action(detail=True, methods=["post"])
    def send_message(self, request, pk=None):
        conversation = self.get_conversation(request, pk)
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            run, _ = self._create_run(
                request, conversation, serializer.validated_data["content"]
            )
        except (DeploymentUnavailable, InvalidExecutionDefinition) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(RunSerializer(run).data, status=202)

    @action(detail=True, methods=["delete"])
    def clear(self, request, pk=None):
        conversation = self.get_conversation(request, pk)
        conversation.messages.all().delete()
        return Response({"detail": "对话已清空"})

    @action(detail=True, methods=["delete"])
    def delete_conversation(self, request, pk=None):
        self.get_conversation(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

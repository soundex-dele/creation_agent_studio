"""Conversation resources backed exclusively by the durable Run plane."""
import logging
import time
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.agents.models import Agent
from apps.agents.runtime import get_agent_definition
from apps.applications.models import Application, Skill
from apps.applications.serializers import application_definition
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
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from modules.execution.application.start_runs import (
    CREATE_AGENT_RUN_OPERATION,
    start_agent_run,
)
from modules.execution.models import IdempotencyRecord, Run

from .models import Conversation, ConversationSkillBinding, Message
from .serializers import (
    ConversationDetailSerializer,
    ConversationListSerializer,
    CreateConversationSerializer,
    SendMessageSerializer,
)


GENERAL_AGENT_SLUG = "general"
logger = logging.getLogger(__name__)


class ConversationRunActive(Exception):
    pass


def resolve_agent(agent_id, organization):
    visible = Agent.objects.filter(
        Q(organization=organization) | Q(is_public=True),
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
            queryset = queryset.filter(chat_application_id=application_id)
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
        if organization is None:
            return Response(
                {"detail": "当前用户没有可用的组织工作区。"},
                status=status.HTTP_403_FORBIDDEN,
            )
        application = None
        chat_application = None
        chat_definition = None
        if data.get("application_id"):
            application = get_object_or_404(
                Application.objects.select_related(
                    "chat_application", "draft").filter(
                    Q(organization=organization)
                    | Q(organization__isnull=True, is_public=True),
                    is_active=True,
                ),
                id=data["application_id"],
                kind=Application.Kind.CHAT,
            )
            chat_application = application.chat_application
            chat_definition = application_definition(application)
        requested_agent_id = data.get("agent_id")
        if application is not None:
            bindings = chat_definition.get("agent_bindings", [])
            binding = next((
                item for item in bindings
                if (item.get("agent_id") == requested_agent_id
                    if requested_agent_id else item.get("is_default"))
            ), None)
            if binding is None:
                return Response(
                    {"agent_id": "该智能体不属于当前聊天应用。"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            agent = get_object_or_404(
                Agent.objects.filter(
                    Q(organization=organization) | Q(is_public=True),
                    is_active=True,
                ),
                id=binding["agent_id"],
            )
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
        for binding in get_agent_definition(agent).get("skill_bindings", []):
            if binding.get("mode") not in ("required", "default"):
                continue
            source = (
                ConversationSkillBinding.Source.AGENT_REQUIRED
                if binding.get("mode") == "required"
                else ConversationSkillBinding.Source.AGENT_DEFAULT
            )
            skill_sources[str(binding["skill_id"])] = (
                source, binding.get("config", {}))
        if application:
            for binding in chat_definition.get("skill_bindings", []):
                if binding.get("mode") not in ("required", "default"):
                    continue
                source = (
                    ConversationSkillBinding.Source.APP_REQUIRED
                    if binding.get("mode") == "required"
                    else ConversationSkillBinding.Source.APP_DEFAULT
                )
                skill_sources[str(binding["skill_id"])] = (
                    source, binding.get("config", {}))
        requested_skills = {str(item) for item in data.get("skill_ids", [])}
        if requested_skills:
            profile = (chat_definition or {}).get("chat_profile", {})
            if application and not profile.get("allow_extra_skills", False):
                allowed = {
                    str(item["skill_id"])
                    for item in chat_definition.get("skill_bindings", [])
                }
                if not requested_skills.issubset(allowed):
                    return Response(
                        {"skill_ids": "包含应用未授权的 Skill。"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            skills = list(Skill.objects.filter(
                id__in=requested_skills,
                is_active=True,
            ).filter(
                Q(visibility=Skill.Visibility.PUBLIC)
                | Q(owner=request.user)
                | Q(organization=organization)
            ))
            if len(skills) != len(requested_skills):
                return Response(
                    {"skill_ids": "包含无权使用的 Skill。"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for skill in skills:
                skill_sources[str(skill.id)] = (
                    ConversationSkillBinding.Source.USER, {})

        with transaction.atomic():
            conversation = Conversation.objects.create(
                user=request.user,
                organization=organization,
                title=data.get("title", ""),
                agent=agent,
                chat_application=chat_application,
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

    @transaction.atomic
    def _create_run(
        self,
        request,
        conversation,
        message,
        idempotency_key,
        requested_agent_id=None,
    ):
        conversation = Conversation.objects.select_for_update().get(
            pk=conversation.pk,
            organization_id=conversation.organization_id,
            user_id=conversation.user_id,
        )
        organization = conversation.organization
        agent = resolve_agent(requested_agent_id or conversation.agent_id, organization)
        is_idempotent_replay = IdempotencyRecord.objects.for_organization(
            organization.id
        ).filter(
            actor=request.user,
            operation=CREATE_AGENT_RUN_OPERATION,
            key=idempotency_key,
        ).exists()
        if not is_idempotent_replay and Run.objects.for_organization(
            organization.id
        ).filter(
            source_type="conversation",
            source_id=str(conversation.id),
            status__in=(
                Run.Status.QUEUED,
                Run.Status.RUNNING,
                Run.Status.WAITING_INPUT,
                Run.Status.WAITING_CHILDREN,
                Run.Status.CANCELLING,
            ),
        ).exists():
            raise ConversationRunActive("当前对话仍在执行，请等待本轮完成后再发送。")
        history = list(
            conversation.messages.order_by("created_at", "id").values("role", "content")
        )[-99:]
        history.append({"role": "user", "content": message})
        run, replayed = start_agent_run(
            organization_id=organization.id,
            agent_id=agent.id,
            actor=request.user,
            environment="production",
            input_data={
                "message": message,
                "messages": history,
                "working_directory": conversation.working_directory,
                "agent_thread": {
                    "provider": conversation.agent_thread_provider,
                    "id": conversation.agent_thread_id,
                } if conversation.agent_thread_id else {},
            },
            idempotency_key=idempotency_key,
            idempotency_input_data={"message": message},
            source_type="conversation",
            source_id=conversation.id,
        )
        if not replayed:
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
        return run, replayed

    @action(detail=True, methods=["post"])
    def send_message(self, request, pk=None):
        started = time.perf_counter()
        logger.info("chat_latency stage=request_received conversation_id=%s", pk)
        conversation = self.get_conversation(request, pk)
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 160:
            return Response(
                {"detail": "Idempotency-Key must contain between 1 and 160 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            run, replayed = self._create_run(
                request,
                conversation,
                serializer.validated_data["content"],
                idempotency_key,
            )
        except (DeploymentUnavailable, InvalidExecutionDefinition) as exc:
            return Response({"detail": str(exc)}, status=409)
        except IdempotencyKeyReused as exc:
            return Response({"detail": str(exc)}, status=409)
        except ConversationRunActive as exc:
            return Response({"detail": str(exc)}, status=409)
        response = Response(RunSerializer(run).data, status=202)
        logger.info(
            "chat_latency stage=run_created conversation_id=%s run_id=%s elapsed_ms=%.1f replayed=%s",
            pk, run.id, (time.perf_counter() - started) * 1000, replayed,
        )
        if replayed:
            response["Idempotent-Replay"] = "true"
        return response

    @action(detail=True, methods=["delete"])
    def clear(self, request, pk=None):
        conversation = self.get_conversation(request, pk)
        with transaction.atomic():
            conversation = Conversation.objects.select_for_update().get(
                pk=conversation.pk,
                organization_id=conversation.organization_id,
                user_id=conversation.user_id,
            )
            conversation.messages.all().delete()
            conversation.agent_thread_provider = ''
            conversation.agent_thread_id = ''
            conversation.save(update_fields=(
                'agent_thread_provider', 'agent_thread_id', 'updated_at',
            ))
        return Response({"detail": "对话已清空"})

    @action(detail=True, methods=["delete"])
    def delete_conversation(self, request, pk=None):
        self.get_conversation(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

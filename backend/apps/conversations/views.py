"""Conversation resources backed exclusively by the durable Run plane."""
import logging
import time
from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.agents.models import Agent, SupervisorProfile
from apps.agents.runtime import get_agent_definition
from apps.applications.models import Application, Skill
from apps.applications.runtime_skills import (
    discover_runtime_skills,
    resolve_runtime_skills,
    resolve_skill_adapter,
)
from apps.applications.serializers import application_definition
from apps.enterprise.permissions import resolve_organization
from apps.projects.models import Project
from apps.projects.services.workspace_files import (
    WorkspaceFileError,
    list_conversation_workspace_files,
    read_conversation_workspace_file,
)
from apps.projects.services.workspace_paths import (
    conversation_working_directory,
    open_workspace_directory,
)
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import (
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from modules.execution.application.start_runs import (
    CREATE_AGENT_RUN_OPERATION,
    CREATE_SUPERVISOR_RUN_OPERATION,
    start_agent_run,
    start_supervisor_run,
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
AGENT_SELECTION_UNSET = object()
logger = logging.getLogger(__name__)


class ConversationRunActive(Exception):
    pass


def resolve_agent(agent_id, organization, *, use_default=False):
    visible = Agent.objects.filter(
        Q(organization=organization) | Q(is_public=True),
        is_active=True,
    )
    if agent_id is None:
        if use_default:
            return get_object_or_404(visible, slug=GENERAL_AGENT_SLUG)
        return None
    selected = visible.filter(pk=agent_id).first()
    if selected is None:
        raise ValidationError({"agent_id": "该智能体不存在或当前用户无权使用。"})
    return selected


def ensure_supervisor_access(agent, user):
    if not agent or agent.kind != Agent.Kind.SUPERVISOR:
        return
    profile = getattr(agent, 'supervisor_profile', None)
    if profile is None:
        raise ValidationError({'agent_id': 'AI 分身配置不完整。'})
    if (
        profile.visibility == SupervisorProfile.Visibility.PRIVATE
        and agent.created_by_id != user.id
        and not user.is_superuser
    ):
        from apps.enterprise.models import Membership
        if not Membership.objects.filter(
            organization=agent.organization,
            user=user,
            is_active=True,
            role__in=(Membership.Role.OWNER, Membership.Role.ADMIN),
        ).exists():
            raise ValidationError({'agent_id': '该 AI 分身为私有。'})


def resolve_conversation_agent(conversation, requested_agent_id):
    """Resolve the runtime Agent and the optional persisted composer selection."""

    if requested_agent_id is AGENT_SELECTION_UNSET:
        return (
            conversation.agent or resolve_agent(
                None, conversation.organization, use_default=True),
            conversation.agent,
        )
    if requested_agent_id is None:
        return (
            resolve_agent(None, conversation.organization, use_default=True),
            None,
        )
    selected = Agent.objects.filter(
        Q(organization=conversation.organization) | Q(is_public=True),
        is_active=True,
        pk=requested_agent_id,
    ).first()
    if selected is None:
        raise ValidationError({"agent_id": "该智能体不存在或当前用户无权使用。"})
    if conversation.application_id:
        allowed = {
            item.get("agent_id")
            for item in application_definition(conversation.application).get(
                "agent_bindings", []
            )
        }
        if selected.id not in allowed:
            raise ValidationError({"agent_id": "该智能体不属于当前聊天应用。"})
    return selected, selected


def validate_requested_skill_names(conversation, requested_skill_names):
    """Validate one-turn Skill names against an application's selection policy."""

    requested = {str(value) for value in requested_skill_names}
    if not requested:
        return
    if conversation.application_id:
        definition = application_definition(conversation.application)
        profile = definition.get("chat_profile") or {}
        if not profile.get("allow_skill_selection", True):
            raise ValidationError({"skill_names": "当前聊天应用不允许选择 Skill。"})
        if not profile.get("allow_extra_skills", False):
            allowed_ids = {
                item.get("skill_id")
                for item in definition.get("skill_bindings", [])
                if item.get("skill_id")
            }
            allowed = set(Skill.objects.filter(
                id__in=allowed_ids,
                is_active=True,
            ).values_list("slug", flat=True))
            if not requested.issubset(allowed):
                raise ValidationError({"skill_names": "包含应用未授权的 Skill。"})


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
        adapter = resolve_skill_adapter()
        return Response({
            "adapter": adapter,
            "skills": discover_runtime_skills(adapter),
        })

    def list(self, request):
        organization = resolve_organization(request)
        queryset = request.user.conversations.filter(organization=organization)
        application_id = request.query_params.get("application_id")
        project_id = request.query_params.get("project_id")
        agent_id = request.query_params.get("agent_id")
        agent_kind = request.query_params.get("agent_kind")
        if agent_id:
            try:
                queryset = queryset.filter(agent_id=int(agent_id))
            except (TypeError, ValueError):
                return Response(
                    {"agent_id": "agent_id 必须是整数。"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if agent_kind:
            if agent_kind not in Agent.Kind.values:
                return Response(
                    {"agent_kind": "未知的智能体类型。"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(agent__kind=agent_kind)
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
        limit = 100 if agent_kind == Agent.Kind.SUPERVISOR else 20
        return Response(ConversationListSerializer(queryset[:limit], many=True).data)

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
        ensure_supervisor_access(agent, request.user)

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
        conversation = self.get_conversation(request, pk)
        from modules.execution.application.projections import (
            repair_conversation_messages,
        )
        repair_conversation_messages(conversation)
        return Response(ConversationDetailSerializer(conversation).data)

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

    @action(detail=True, methods=["post"], url_path="open-workspace")
    def open_workspace(self, request, pk=None):
        if not settings.LOCAL_FILE_MANAGER_ENABLED:
            return Response(
                {"detail": "当前部署不支持打开本机目录。"},
                status=status.HTTP_409_CONFLICT,
            )
        conversation = self.get_conversation(request, pk)
        try:
            directory = conversation_working_directory(conversation)
            open_workspace_directory(directory)
        except (FileNotFoundError, OSError):
            logger.exception(
                "Unable to open conversation workspace conversation_id=%s", pk,
            )
            return Response(
                {"detail": "无法打开当前会话目录。"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"working_directory": directory})

    def _create_run(
        self,
        request,
        conversation,
        message,
        idempotency_key,
        requested_agent_id=AGENT_SELECTION_UNSET,
        requested_skill_names=(),
        max_retries=6,
    ):
        for retry_no in range(max_retries):
            try:
                return self._create_run_once(
                    request,
                    conversation,
                    message,
                    idempotency_key,
                    requested_agent_id=requested_agent_id,
                    requested_skill_names=requested_skill_names,
                )
            except OperationalError as exc:
                is_busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not is_busy or retry_no + 1 >= max_retries:
                    raise
                time.sleep(0.02 * (2**retry_no))

        raise RuntimeError("Unable to create conversation run after retries")

    @transaction.atomic
    def _create_run_once(
        self,
        request,
        conversation,
        message,
        idempotency_key,
        requested_agent_id=AGENT_SELECTION_UNSET,
        requested_skill_names=(),
    ):
        conversation = Conversation.objects.select_for_update().get(
            pk=conversation.pk,
            organization_id=conversation.organization_id,
            user_id=conversation.user_id,
        )
        organization = conversation.organization
        agent, selected_agent = resolve_conversation_agent(
            conversation, requested_agent_id)
        selection_changed = conversation.agent_id != getattr(
            selected_agent, "id", None)
        ensure_supervisor_access(agent, request.user)
        operation = (
            CREATE_SUPERVISOR_RUN_OPERATION
            if agent.kind == Agent.Kind.SUPERVISOR
            else CREATE_AGENT_RUN_OPERATION
        )
        is_idempotent_replay = IdempotencyRecord.objects.for_organization(
            organization.id
        ).filter(
            actor=request.user,
            operation=operation,
            key=idempotency_key,
        ).exists()
        if not is_idempotent_replay and Run.objects.for_organization(
            organization.id
        ).filter(
            Q(source_type="conversation", source_id=str(conversation.id))
            | Q(
                source_type="supervisor",
                definition_snapshot__conversation_id=str(conversation.id),
            )
            | Q(
                source_type="supervisor_task",
                definition_snapshot__conversation_id=str(conversation.id),
            ),
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
        working_directory = conversation_working_directory(conversation)
        validate_requested_skill_names(conversation, requested_skill_names)
        if agent.kind == Agent.Kind.SUPERVISOR:
            run, replayed = start_supervisor_run(
                organization_id=organization.id,
                supervisor_id=agent.id,
                actor=request.user,
                goal=message,
                context={
                    "messages": history[:-1],
                    "working_directory": working_directory,
                },
                conversation_id=conversation.id,
                idempotency_key=idempotency_key,
            )
            if not replayed:
                if not conversation.title:
                    conversation.title = message[:50]
                conversation.save(update_fields=["title", "updated_at"])
                Message.objects.create(
                    conversation=conversation,
                    run=run,
                    role="user",
                    content=message,
                    metadata={"supervisor": True},
                )
            return run, replayed

        definition = get_agent_definition(agent)
        adapter = resolve_skill_adapter(
            (definition.get("model_config") or {}).get("adapter")
            or settings.AGENT_ENGINE_ADAPTER
        )
        effective_skill_names = [
            binding.skill.slug
            for binding in conversation.skill_bindings.select_related("skill").filter(
                enabled=True,
                skill__is_active=True,
            ).exclude(source__in=(
                ConversationSkillBinding.Source.AGENT_REQUIRED,
                ConversationSkillBinding.Source.AGENT_DEFAULT,
            ))
        ]
        effective_skill_names.extend(requested_skill_names)
        try:
            skill_inputs = resolve_runtime_skills(effective_skill_names, adapter)
        except ValueError as exc:
            raise ValidationError({"skill_names": str(exc)}) from exc
        run, replayed = start_agent_run(
            organization_id=organization.id,
            agent_id=agent.id,
            actor=request.user,
            input_data={
                "message": message,
                "messages": history,
                "working_directory": working_directory,
                "skills": skill_inputs,
                # Agent selection changes the instructions, not the conversation
                # identity. Supplying the persisted thread makes Codex use
                # thread/resume with the newly selected Agent's system prompt.
                "agent_thread": {
                    "provider": conversation.agent_thread_provider,
                    "id": conversation.agent_thread_id,
                } if conversation.agent_thread_id else {},
            },
            idempotency_key=idempotency_key,
            idempotency_input_data={
                "message": message,
                "skill_names": sorted(
                    str(value) for value in requested_skill_names),
            },
            source_type="conversation",
            source_id=conversation.id,
            allow_draft=True,
            definition_overrides=(
                {"system_prompt": ""} if selected_agent is None else None
            ),
        )
        if not replayed:
            update_fields = ["title", "updated_at"]
            if selection_changed:
                conversation.agent = selected_agent
                update_fields.append("agent")
            if not conversation.title:
                conversation.title = message[:50]
            conversation.save(update_fields=update_fields)
            Message.objects.create(
                conversation=conversation,
                role="user",
                content=message,
                metadata={
                    "run_request_id": getattr(request, "request_id", ""),
                    "composer": {
                        "agent_id": getattr(selected_agent, "id", None),
                        "skill_names": sorted(
                            str(value) for value in requested_skill_names),
                        "skills": [item["name"] for item in skill_inputs],
                    },
                },
            )
        return run, replayed

    @action(detail=True, methods=["post"])
    def send_message(self, request, pk=None):
        started = time.perf_counter()
        logger.info("chat_latency stage=request_received conversation_id=%s", pk)
        conversation = self.get_conversation(request, pk)
        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "chat_validation stage=send_message_invalid conversation_id=%s errors=%s",
                pk, serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
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
                requested_agent_id=serializer.validated_data.get(
                    "agent_id", AGENT_SELECTION_UNSET),
                requested_skill_names=serializer.validated_data.get(
                    "skill_names", ()),
            )
        except ValidationError as exc:
            logger.warning(
                "chat_validation stage=composer_selection_invalid conversation_id=%s errors=%s",
                pk, exc.detail,
            )
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
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
        conversation = self.get_conversation(request, pk)
        with transaction.atomic():
            conversation = Conversation.objects.select_for_update().get(
                pk=conversation.pk,
                organization_id=conversation.organization_id,
                user_id=conversation.user_id,
            )
            has_active_run = Run.objects.for_organization(
                conversation.organization_id
            ).filter(
                Q(source_type="conversation", source_id=str(conversation.id))
                | Q(
                    source_type="supervisor",
                    definition_snapshot__conversation_id=str(conversation.id),
                )
                | Q(
                    source_type="supervisor_task",
                    definition_snapshot__conversation_id=str(conversation.id),
                ),
                status__in=(
                    Run.Status.QUEUED,
                    Run.Status.RUNNING,
                    Run.Status.WAITING_INPUT,
                    Run.Status.WAITING_CHILDREN,
                    Run.Status.CANCELLING,
                ),
            ).exists()
            if has_active_run:
                instance_name = (
                    "分身实例"
                    if conversation.agent
                    and conversation.agent.kind == Agent.Kind.SUPERVISOR
                    else "对话"
                )
                return Response(
                    {
                        "detail": (
                            f"当前{instance_name}仍在执行，请先等待任务结束"
                            "或取消任务后再删除。"
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

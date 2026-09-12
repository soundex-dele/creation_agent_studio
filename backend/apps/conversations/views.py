"""
Views for conversations app.
"""
import json
import logging
import time
import uuid
from pathlib import Path
from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from apps.agents.models import Agent
from apps.agents.runtime import get_agent_definition
from apps.applications.models import Application, Skill
from apps.applications.serializers import application_definition
from apps.projects.models import Project
from apps.projects.services.asset_collector import collect_assets_from_message
from apps.projects.services.workspace_files import (
    WorkspaceFileError,
    list_conversation_workspace_files,
    read_conversation_workspace_file,
)
from apps.projects.services.workspace_paths import conversation_working_directory
from .agent_protocol import (
    ensure_agent_thread,
    finish_agent_turn,
    record_server_requests,
    start_agent_turn,
    update_turn_remote_id,
)
from .models import (
    AgentServerRequest,
    AgentTurn,
    Conversation,
    ConversationSkillBinding,
    Message,
)
from .serializers import (
    ConversationListSerializer,
    ConversationDetailSerializer,
    CreateConversationSerializer,
    SendMessageSerializer,
    MessageSerializer,
    StreamMessageSerializer,
    ResumeAgentSerializer,
)
from core.agent_engine.adapters import AgentEvent, EventType, ProgressCategory
from core.agent_engine.protocol import ProtocolProjector, encode_sse
from core.agent_engine.runtime import event_payload, normalize_event, session_registry
from core.llm.factory import build_agent_engine
from core.llm.prompt_manager import PromptManager

GENERAL_AGENT_SLUG = 'general'
logger = logging.getLogger(__name__)


def resolve_agent(agent_id):
    """解析对话绑定的智能体。未提供或无效时回退到通用 agent (slug=general)。"""
    if agent_id is not None:
        agent = Agent.objects.filter(pk=agent_id, is_public=True).first()
        if agent is not None:
            logger.info("resolve_agent: agent_id=%s -> slug=%s name=%s",
                        agent_id, agent.slug, agent.name)
            return agent
        logger.info("resolve_agent: agent_id=%s not found, falling back to general", agent_id)
    else:
        logger.info("resolve_agent: no agent_id provided, falling back to general")
    return Agent.objects.get(slug=GENERAL_AGENT_SLUG)


def resolve_system_prompt(conversation) -> str:
    """返回对话所绑定 agent 的 system_prompt；未绑定（旧数据）时回退到全局默认。"""
    if conversation.agent:
        prompt = get_agent_definition(conversation.agent).get('system_prompt', '')
        if not prompt:
            prompt = PromptManager.SYSTEM_PROMPT
        logger.info(
            "resolve_system_prompt: conversation=%s agent=%s slug=%s prompt_prefix=%r",
            conversation.id, conversation.agent.name, conversation.agent.slug, prompt[:40],
        )
        return prompt
    logger.info("resolve_system_prompt: conversation=%s has no agent, using global default",
                conversation.id)
    return PromptManager.SYSTEM_PROMPT


def resolve_adapter_config(agent) -> tuple[str, dict]:
    """Read adapter selection from the agent's deployed definition."""
    model_config = get_agent_definition(agent).get('model_config', {}) if agent else {}
    return (
        (model_config.get('adapter') or settings.AGENT_ENGINE_ADAPTER).strip().lower(),
        {'model': model_config.get('model', '')},
    )


class ConversationViewSet(viewsets.ViewSet):
    """对话视图集"""
    permission_classes = [IsAuthenticated]

    def get_conversation(self, request, pk):
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request)
        return get_object_or_404(
            Conversation.objects.filter(
                Q(organization=organization) | Q(organization__isnull=True)
            ),
            pk=pk,
            user=request.user,
        )

    @action(detail=False, methods=['get'], url_path='composer-options')
    def composer_options(self, request):
        """Return skills available to the chat composer."""
        skills_root = Path(
            settings.GRAPHFLOW_SKILLS_DIRECTORY
            or (Path.home() / '.graphflow' / 'skills')
        )
        skills = []
        if skills_root.is_dir():
            for skill_file in sorted(skills_root.glob('*/SKILL.md')):
                name = skill_file.parent.name
                description = ''
                try:
                    for line in skill_file.read_text(encoding='utf-8').splitlines():
                        stripped = line.strip()
                        if stripped.startswith('description:'):
                            description = stripped.split(':', 1)[1].strip().strip('"\'')
                            break
                        text = line.strip().lstrip('#').strip()
                        if text and text != '---' and not text.startswith('name:'):
                            description = text
                            break
                except OSError:
                    pass
                skills.append({'name': name, 'description': description})
        return Response({'skills': skills})

    def list(self, request):
        """获取对话列表"""
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request)
        queryset = request.user.conversations.filter(
            Q(organization=organization) | Q(organization__isnull=True)
        )

        workflow_step_run_id = request.query_params.get('workflow_step_run_id')
        application_id = request.query_params.get('application_id')
        project_id = request.query_params.get('project_id')
        if workflow_step_run_id:
            queryset = queryset.filter(workflow_step_run_id=workflow_step_run_id)
        elif application_id:
            queryset = queryset.filter(chat_application_id=application_id)
            if project_id:
                queryset = queryset.filter(project_id=project_id)
        elif project_id:
            # Workspace-scoped listing (optionally narrowed to a single process)
            queryset = queryset.filter(project_id=project_id)
            process_id = request.query_params.get('process_id')
            if process_id:
                queryset = queryset.filter(process_id=process_id)
        else:
            # Home chat list: hide conversations that belong to a workspace
            queryset = queryset.filter(project__isnull=True)

        # 应用搜索过滤
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(title__icontains=search)

        conversations = queryset[:20]
        serializer = ConversationListSerializer(conversations, many=True)
        return Response(serializer.data)

    def create(self, request):
        """创建普通对话，或创建绑定聊天应用/工作流步骤的对话。"""
        serializer = CreateConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request)
        application = None
        chat_application = None
        chat_definition = None
        workflow_step_run = None
        application_id = data.get('application_id')
        workflow_step_run_id = data.get('workflow_step_run_id')
        if workflow_step_run_id:
            from apps.workflows.models import WorkflowStepRun
            workflow_step_run = get_object_or_404(
                WorkflowStepRun.objects.select_related(
                    'workflow_run__project', 'workflow_run__started_by',
                    'application', 'application_revision'),
                id=workflow_step_run_id,
                workflow_run__started_by=request.user,
            )
            application = workflow_step_run.application
            chat_definition = workflow_step_run.application_revision.content
            if application_id and application.id != application_id:
                return Response(
                    {'application_id': '与工作流步骤中的应用不一致。'},
                    status=status.HTTP_400_BAD_REQUEST)
        elif application_id:
            application = get_object_or_404(
                Application.objects.select_related('chat_application', 'draft').filter(
                    Q(is_public=True) | Q(organization=organization) |
                    Q(created_by=request.user)),
                id=application_id)
            chat_application = application.chat_application
            chat_definition = application_definition(application)

        requested_agent_id = data.get('agent_id')
        if application:
            if application.kind != Application.Kind.CHAT:
                return Response({'detail': '只有聊天应用可以创建对话。'}, status=400)
            agent_bindings = chat_definition.get('agent_bindings', [])
            if requested_agent_id:
                binding = next((item for item in agent_bindings
                                if item.get('agent_id') == requested_agent_id), None)
            else:
                binding = next((item for item in agent_bindings
                                if item.get('is_default')), None)
            if binding is None:
                return Response({'agent_id': '该智能体不属于当前聊天应用。'},
                                status=status.HTTP_400_BAD_REQUEST)
            agent = get_object_or_404(Agent, id=binding['agent_id'])
        else:
            agent = resolve_agent(requested_agent_id)

        # Optionally bind the conversation to a project and workflow step.
        project = None
        project_id = data.get('project_id')
        if workflow_step_run:
            project = workflow_step_run.workflow_run.project
        elif project_id:
            project = get_object_or_404(
                Project.objects.filter(
                    Q(organization=organization) | Q(organization__isnull=True)),
                id=project_id,
                user=request.user,
            )
        requested_working_directory = data.get('working_directory', '')
        if requested_working_directory and (application or project):
            return Response(
                {'working_directory': '应用或项目对话必须使用其自己的工作目录。'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if application and project and not workflow_step_run:
            if (
                project.application_id is None
                and not project.workflow_id
                and not project.working_directory
            ):
                # Backward compatibility for application workspaces created
                # before Project.application/working_directory existed.
                project.application = application
                project.save(update_fields=['application'])
            if project.application_id != application.id:
                return Response(
                    {'project_id': '该工作空间不属于当前应用。'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        process_id = data.get('process_id', '') or ''

        skill_sources = {}
        if agent:
            for binding in get_agent_definition(agent).get('skill_bindings', []):
                if binding.get('mode') not in ('required', 'default'):
                    continue
                source = (ConversationSkillBinding.Source.AGENT_REQUIRED
                          if binding.get('mode') == 'required'
                          else ConversationSkillBinding.Source.AGENT_DEFAULT)
                skill_sources[str(binding['skill_id'])] = (
                    source, binding.get('config', {}))
        if application:
            for binding in chat_definition.get('skill_bindings', []):
                if binding.get('mode') not in ('required', 'default'):
                    continue
                source = (ConversationSkillBinding.Source.APP_REQUIRED
                          if binding.get('mode') == 'required'
                          else ConversationSkillBinding.Source.APP_DEFAULT)
                skill_sources[str(binding['skill_id'])] = (
                    source, binding.get('config', {}))
        requested_skills = {str(item) for item in data.get('skill_ids', [])}
        if requested_skills:
            profile = (chat_definition or {}).get('chat_profile', {})
            if application and not profile.get('allow_extra_skills', False):
                allowed = {str(item['skill_id']) for item in
                           chat_definition.get('skill_bindings', [])}
                if not requested_skills.issubset(allowed):
                    return Response({'skill_ids': '包含应用未授权的 Skill。'},
                                    status=status.HTTP_400_BAD_REQUEST)
            skills = list(Skill.objects.filter(
                id__in=requested_skills, is_active=True).filter(
                    (Q(visibility='public') |
                     Q(owner=request.user) |
                     (Q(organization=organization)
                      if organization is not None else Q(pk__in=[])))))
            if len(skills) != len(requested_skills):
                return Response({'skill_ids': '包含无权使用的 Skill。'},
                                status=status.HTTP_400_BAD_REQUEST)
            for skill in skills:
                skill_sources[str(skill.id)] = (
                    ConversationSkillBinding.Source.USER, {})
        with transaction.atomic():
            conversation = Conversation.objects.create(
                user=request.user,
                organization=organization,
                title=data.get('title', ''),
                agent=agent,
                chat_application=(chat_application if not workflow_step_run else None),
                workflow_step_run=workflow_step_run,
                project=project,
                process_id=process_id,
                working_directory=requested_working_directory,
            )
            conversation_working_directory(conversation)
            ConversationSkillBinding.objects.bulk_create([
                ConversationSkillBinding(
                    conversation=conversation, skill_id=skill_id,
                    source=source, config=config)
                for skill_id, (source, config) in skill_sources.items()
            ])

        return Response(
            ConversationListSerializer(conversation).data,
            status=status.HTTP_201_CREATED
        )

    def retrieve(self, request, pk=None):
        """获取对话详情"""
        conversation = self.get_conversation(request, pk)
        serializer = ConversationDetailSerializer(conversation)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='workspace-files')
    def workspace_files(self, request, pk=None):
        """列出或预览当前对话实际使用的工作目录文件。"""
        conversation = self.get_conversation(request, pk)
        relative_path = request.query_params.get('path')
        try:
            if relative_path is not None:
                return Response(read_conversation_workspace_file(
                    conversation, relative_path))
            return Response(list_conversation_workspace_files(conversation))
        except WorkspaceFileError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError:
            return Response(
                {'detail': '文件不存在或已被删除。'},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        """发送消息"""
        conversation = self.get_conversation(request, pk)
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        content = serializer.validated_data['content']
        from apps.enterprise.services import apply_input_guardrails
        content = apply_input_guardrails(conversation.organization, content)
        from apps.enterprise.services import enforce_quota
        enforce_quota(conversation.organization)
        started_at = time.monotonic()
        trace = None
        if conversation.organization:
            from apps.enterprise.models import RunTrace
            trace = RunTrace.objects.create(
                organization=conversation.organization, user=request.user,
                kind='conversation', resource_id=str(conversation.id),
                status=RunTrace.Status.RUNNING, input={'message': content},
                started_at=timezone.now())

        # 保存用户消息
        user_message = Message.objects.create(
            conversation=conversation,
            role='user',
            content=content
        )

        # 获取对话历史
        messages = conversation.messages.values('role', 'content')
        history = list(messages)

        # 构建 LLM 消息（使用对话所绑定 agent 的 system_prompt）
        llm_messages = PromptManager.build_messages(
            history,
            content,
            resolve_system_prompt(conversation)
        )

        # 调用 LLM
        try:
            adapter_name, adapter_options = resolve_adapter_config(conversation.agent)
            engine = build_agent_engine(
                conversation.organization,
                adapter_options['model'],
                adapter_name=adapter_name,
                working_directory=conversation_working_directory(conversation),
            )
            response = engine.complete(llm_messages)
            if not response.success:
                raise ValueError(response.error or 'LLM 请求失败')

            # 提取助手回复
            from apps.enterprise.services import apply_output_guardrails
            assistant_content = apply_output_guardrails(
                conversation.organization, response.content)

            # 保存助手消息
            assistant_message = Message.objects.create(
                conversation=conversation,
                role='assistant',
                content=assistant_content,
                metadata={'usage': response.usage.model_dump(), 'model': response.model},
            )

            from apps.enterprise.services import record_usage
            record_usage(
                organization=conversation.organization, user=request.user,
                resource_type='conversation', resource_id=conversation.id,
                usage=response.usage.model_dump(), model=response.model,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if trace:
                trace.status = RunTrace.Status.SUCCEEDED
                trace.output = {'message_id': str(assistant_message.id)}
                trace.finished_at = timezone.now()
                trace.save(update_fields=['status', 'output', 'finished_at'])

            # 自动收集生成内容到工作空间（图片/文本）
            if conversation.project:
                try:
                    collect_assets_from_message(
                        conversation.project, conversation, assistant_message)
                except Exception as e:
                    logger.warning("asset collection failed (send_message): %s", e)

            # 更新对话标题（如果还没有标题）
            if not conversation.title:
                conversation.title = content[:50]
                conversation.save()

            return Response({
                'user_message': MessageSerializer(user_message).data,
                'assistant_message': MessageSerializer(assistant_message).data
            })

        except Exception as e:
            if trace:
                trace.status = RunTrace.Status.FAILED
                trace.error = str(e)
                trace.finished_at = timezone.now()
                trace.save(update_fields=['status', 'error', 'finished_at'])
            return Response(
                {'detail': f'LLM 调用失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['delete'])
    def clear(self, request, pk=None):
        """清空对话"""
        conversation = self.get_conversation(request, pk)
        session_registry.remove(str(conversation.id))
        conversation.messages.all().delete()
        return Response({'detail': '对话已清空'})

    @action(detail=True, methods=['delete'])
    def delete_conversation(self, request, pk=None):
        """删除对话"""
        conversation = self.get_conversation(request, pk)
        session_registry.remove(str(conversation.id))
        conversation.delete()
        return Response({'detail': '对话已删除'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def stream(self, request, pk=None):
        """Stream normalized agent events and keep the turn alive for control."""
        conversation = self.get_conversation(request, pk)
        serializer = StreamMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = serializer.validated_data['message']
        protocol_version = int(serializer.validated_data['protocol_version'])
        from apps.enterprise.services import apply_input_guardrails
        content = apply_input_guardrails(conversation.organization, content)
        from apps.enterprise.services import enforce_quota
        enforce_quota(conversation.organization)
        permission_mode = serializer.validated_data['permission_mode']
        if permission_mode == 'allow_all':
            from apps.enterprise.models import Membership
            membership = getattr(request, 'organization_membership', None)
            may_bypass = request.user.role == 'admin' or (
                membership and membership.role in (
                    Membership.Role.OWNER, Membership.Role.ADMIN))
        else:
            may_bypass = True
        if not may_bypass:
            return Response(
                {'permission_mode': 'Only administrators may bypass tool approval.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        selected_skills = serializer.validated_data['skills']
        if not selected_skills:
            selected_skills = list(
                conversation.skill_bindings.filter(enabled=True).values_list(
                    'skill__slug', flat=True))
        from apps.enterprise.services import enforce_skill_policy
        selected_skills = enforce_skill_policy(conversation.organization, selected_skills)
        if 'agent_id' in serializer.validated_data:
            requested_agent_id = serializer.validated_data.get('agent_id')
            effective_agent = (
                get_object_or_404(
                    Agent.objects.filter(
                        Q(is_public=True) | Q(created_by=request.user)
                    ),
                    pk=requested_agent_id,
                )
                if requested_agent_id is not None else None
            )
        else:
            effective_agent = conversation.agent

        history = list(conversation.messages.values('role', 'content'))

        Message.objects.create(
            conversation=conversation,
            role='user',
            content=content,
            metadata={
                'composer': {
                    'skills': selected_skills,
                    'agent_id': effective_agent.id if effective_agent else None,
                    'permission_mode': permission_mode,
                }
            },
        )
        update_fields = []
        effective_agent_id = effective_agent.id if effective_agent else None
        if conversation.agent_id != effective_agent_id:
            conversation.agent = effective_agent
            update_fields.append('agent')
        if not conversation.title:
            conversation.title = content[:50]
            update_fields.append('title')
        if update_fields:
            conversation.save(update_fields=[*update_fields, 'updated_at'])

        def event_stream():
            session = None
            acquired = False
            last_engine_event = None
            segments_flushed = False
            protocol_thread = None
            protocol_turn = None
            protocol_projector = None
            protocol_started = False
            protocol_finished = False
            protocol_terminal_status = None
            protocol_terminal_error = None
            # Request-local cache. Streaming events only mutate these segments;
            # database writes are deferred until the stream ends or disconnects.
            display_segments = []
            active_content_index = None
            tool_segment_indexes = {}
            loaded_skills = []

            def record_content(value, *, snapshot=False):
                nonlocal active_content_index
                if not value:
                    return None
                if active_content_index is None:
                    active_content_index = len(display_segments)
                    display_segments.append({
                        'kind': 'content',
                        'content': value,
                    })
                else:
                    if snapshot:
                        display_segments[active_content_index]['content'] = value
                    else:
                        # GraphFlow publishes streaming content as deltas.
                        display_segments[active_content_index]['content'] += value
                return active_content_index

            def record_tool(tool_call):
                nonlocal active_content_index
                active_content_index = None
                tool_key = tool_call.get('id') or tool_call.get('name')
                segment_index = tool_segment_indexes.get(tool_key)
                if segment_index is None:
                    segment_index = len(display_segments)
                    tool_segment_indexes[tool_key] = segment_index
                    display_segments.append({
                        'kind': 'tool',
                        'tool_call': tool_call,
                    })
                    return segment_index
                previous = display_segments[segment_index]['tool_call']
                display_segments[segment_index]['tool_call'] = {
                    **previous,
                    **tool_call,
                }
                return segment_index

            def persist_segment(index, engine_event, *, lifecycle='streaming',
                                usage=None):
                """Persist one cached visible segment."""
                if index is None:
                    return None
                segment = display_segments[index]
                session_adapter = getattr(session, 'adapter_name', None)
                if not isinstance(session_adapter, str):
                    session_adapter = adapter_name
                agent_metadata = {
                    'agent_id': engine_event.agent_id,
                    'query_id': engine_event.query_id,
                    'adapter': session_adapter,
                    'message_kind': segment['kind'],
                    'lifecycle': lifecycle,
                }
                if segment['kind'] == 'tool':
                    agent_metadata['tool_calls'] = [segment['tool_call']]
                if loaded_skills and index == 0:
                    agent_metadata['loaded_skills'] = loaded_skills
                if usage is not None:
                    agent_metadata['usage'] = usage
                # `agent` is provider-neutral. Keep `graphflow` during the v1
                # compatibility window for already-deployed clients.
                metadata = {
                    'agent': agent_metadata,
                    'graphflow': agent_metadata,
                }
                message_id = segment.get('message_id')
                if message_id:
                    Message.objects.filter(pk=message_id).update(
                        content=segment.get('content', ''),
                        metadata=metadata,
                    )
                    return Message.objects.get(pk=message_id)
                message = Message.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=segment.get('content', ''),
                    metadata=metadata,
                )
                segment['message_id'] = message.id
                return message

            def flush_segments(engine_event, *, lifecycle='streaming', usage=None):
                """Flush the request-local segment cache to the database once."""
                nonlocal segments_flushed
                if segments_flushed or engine_event is None:
                    return []
                assistant_messages = []
                for index, _segment in enumerate(display_segments):
                    is_last = index == len(display_segments) - 1
                    assistant_messages.append(persist_segment(
                        index,
                        engine_event,
                        lifecycle=lifecycle,
                        usage=usage if is_last else None,
                    ))
                segments_flushed = True
                return assistant_messages
            try:
                adapter_name, adapter_options = resolve_adapter_config(effective_agent)
                provider_override = None
                content_progress_mode = (
                    'snapshot'
                    if settings.GRAPHFLOW_PROVIDER == 'anthropic'
                    else 'delta'
                )
                if conversation.organization and adapter_name == 'graphflow':
                    from apps.enterprise.services import resolve_provider
                    routed = resolve_provider(conversation.organization)
                    if routed:
                        provider = routed['provider']
                        content_progress_mode = (
                            'snapshot'
                            if provider.provider_type == 'anthropic'
                            else 'delta'
                        )
                        provider_override = {
                            'provider': provider.provider_type,
                            'api_key': routed['api_key'],
                            'base_url': provider.base_url,
                            'model': routed['model'] or settings.GRAPHFLOW_MODEL,
                        }
                session = session_registry.get_or_create(
                    str(conversation.id),
                    system_prompt=(
                        get_agent_definition(effective_agent).get('system_prompt', '')
                        or PromptManager.SYSTEM_PROMPT
                        if effective_agent else PromptManager.SYSTEM_PROMPT
                    ),
                    enable_permissions=permission_mode != 'allow_all',
                    provider_override=provider_override,
                    adapter_name=adapter_name,
                    adapter_options=adapter_options,
                    working_directory=conversation_working_directory(conversation),
                )
                session_content_mode = getattr(session, 'content_mode', None)
                if session_content_mode in ('delta', 'snapshot'):
                    content_progress_mode = session_content_mode
                acquired = session.stream_lock.acquire(blocking=False)
                if not acquired:
                    raise RuntimeError(
                        'This conversation already has an active agent turn.'
                    )
                protocol_thread = ensure_agent_thread(
                    conversation,
                    provider=adapter_name,
                    remote_id=str(session.agent_id),
                    config={
                        'model': adapter_options.get('model') or '',
                        'workingDirectory': conversation_working_directory(
                            conversation
                        ),
                    },
                )
                protocol_turn = start_agent_turn(protocol_thread, text=content)
                protocol_projector = ProtocolProjector(
                    thread_id=str(protocol_thread.id),
                    turn_id=str(protocol_turn.id),
                )
                run_content = content
                context_parts = []
                if getattr(session, 'is_new', False) and history:
                    transcript = '\n'.join(
                        f"{item['role']}: {item['content']}" for item in history
                    )
                    context_parts.append(
                        'Conversation history before this request:\n' + transcript
                    )
                if context_parts:
                    run_content = (
                        '[Composer context]\n'
                        + '\n'.join(context_parts)
                        + '\n\n'
                        + content
                    )
                session.submit(
                    run_content,
                    system_prompt=(
                        get_agent_definition(effective_agent).get('system_prompt', '')
                        or PromptManager.SYSTEM_PROMPT
                        if effective_agent else PromptManager.SYSTEM_PROMPT
                    ),
                    preload_skills=selected_skills,
                )
                session.is_new = False
                if protocol_version == 2:
                    yield protocol_projector.start_turn().to_sse()
                    protocol_started = True

                while True:
                    engine_event = session.wait_for_event(timeout=15.0)
                    if engine_event is None:
                        yield ': heartbeat\n\n'
                        continue
                    engine_event = normalize_event(engine_event)
                    if engine_event.agent_id != session.agent_id:
                        continue
                    last_engine_event = engine_event

                    if (
                        engine_event.type == EventType.PROGRESS
                        and engine_event.progress_category
                        == ProgressCategory.CONTENT
                    ):
                        engine_event.extras['content_mode'] = content_progress_mode
                    payload = event_payload(engine_event)
                    update_turn_remote_id(protocol_turn, engine_event.query_id)
                    protocol_events = protocol_projector.project(engine_event)
                    record_server_requests(
                        protocol_thread, protocol_turn, protocol_events
                    )
                    if payload.get('loaded_skills') is not None:
                        loaded_skills = payload['loaded_skills']
                    if (
                        payload.get('is_assistant_content')
                        and engine_event.content
                    ):
                        payload['content_mode'] = content_progress_mode
                        record_content(
                            engine_event.content,
                            snapshot=content_progress_mode == 'snapshot',
                        )
                    if engine_event.type in (
                        EventType.TOOL_START,
                        EventType.TOOL_END,
                    ) and payload.get('tool_call'):
                        record_tool(payload['tool_call'])

                    # Completion is a lifecycle event and is not rendered by
                    # clients. Older native runtimes may put final text only on
                    # COMPLETED, so surface it as Content progress immediately
                    # before the terminal event. New runtimes already emitted
                    # the same snapshot and are deduplicated here.
                    if (
                        engine_event.type == EventType.COMPLETED
                        and engine_event.content
                        and (
                            active_content_index is None
                            or display_segments[active_content_index]['content']
                            != engine_event.content
                        )
                    ):
                        record_content(
                            engine_event.content, snapshot=True)
                        progress_payload = {
                            **payload,
                            'type': EventType.PROGRESS,
                            'content': engine_event.content,
                            'progress_category': ProgressCategory.CONTENT,
                            'is_assistant_content': True,
                            'content_mode': 'snapshot',
                        }
                        if protocol_version == 1:
                            yield (
                                'event: engine\ndata: '
                                + json.dumps(progress_payload, ensure_ascii=False)
                                + '\n\n'
                            )

                    if protocol_version == 2:
                        if protocol_events:
                            yield encode_sse(protocol_events)
                    else:
                        yield (
                            'event: engine\ndata: '
                            + json.dumps(payload, ensure_ascii=False)
                            + '\n\n'
                        )

                    if engine_event.type == EventType.COMPLETED:
                        assistant_messages = flush_segments(
                            engine_event,
                            lifecycle='completed',
                            usage=payload.get('usage', {}),
                        )
                        for assistant_message in assistant_messages:
                            if conversation.project and assistant_message.content:
                                try:
                                    collect_assets_from_message(
                                        conversation.project,
                                        conversation,
                                        assistant_message,
                                    )
                                except Exception as exc:
                                    logger.warning(
                                        'asset collection failed (stream): %s', exc
                                    )
                        finish_agent_turn(
                            protocol_turn,
                            status=AgentTurn.Status.COMPLETED,
                            items=protocol_projector.snapshot_items(),
                            usage=payload.get('usage', {}),
                        )
                        protocol_finished = True
                        done_data = json.dumps({
                            'conversation_id': str(conversation.id),
                            'message_id': (
                                str(assistant_messages[-1].id)
                                if assistant_messages else ''
                            ),
                            'tokens_used': payload.get('usage', {}).get(
                                'total_tokens', 0
                            ),
                            'type': 'done',
                        }, ensure_ascii=False)
                        from apps.enterprise.services import record_usage
                        record_usage(
                            organization=conversation.organization,
                            user=request.user,
                            resource_type='conversation_stream',
                            resource_id=conversation.id,
                            usage=payload.get('usage', {}),
                            provider=(
                                session.adapter_name
                                if isinstance(getattr(session, 'adapter_name', None), str)
                                else adapter_name
                            ),
                            model=adapter_options.get('model') or (
                                settings.GRAPHFLOW_MODEL
                                if adapter_name == 'graphflow'
                                else settings.CODEX_MODEL
                            ),
                            status='success',
                        )
                        yield f'event: done\ndata: {done_data}\n\n'
                        break

                    if engine_event.type in (
                        EventType.FAILED,
                        EventType.CANCELLED,
                    ):
                        protocol_terminal_status = (
                            AgentTurn.Status.FAILED
                            if engine_event.type == EventType.FAILED
                            else AgentTurn.Status.INTERRUPTED
                        )
                        if engine_event.error_message:
                            protocol_terminal_error = {
                                'code': engine_event.error_code or 'agent_error',
                                'message': engine_event.error_message,
                            }
                        break
            except GeneratorExit:
                protocol_terminal_status = AgentTurn.Status.INTERRUPTED
                if session is not None:
                    try:
                        session.cancel()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                protocol_terminal_status = AgentTurn.Status.FAILED
                protocol_terminal_error = {
                    'code': 'agent_error',
                    'message': str(exc),
                }
                if protocol_version == 2:
                    if protocol_projector is None:
                        protocol_projector = ProtocolProjector(
                            thread_id=(
                                str(protocol_thread.id)
                                if protocol_thread is not None
                                else str(conversation.id)
                            ),
                            turn_id=(
                                str(protocol_turn.id)
                                if protocol_turn is not None
                                else f'failed-{uuid.uuid4().hex}'
                            ),
                        )
                    if not protocol_started:
                        yield protocol_projector.start_turn().to_sse()
                        protocol_started = True
                    failure_event = AgentEvent(
                        type=EventType.FAILED,
                        agent_id=str(getattr(session, 'agent_id', '')),
                        error_code='agent_error',
                        error_message=str(exc),
                    )
                    yield encode_sse(protocol_projector.project(failure_event))
                else:
                    error_data = json.dumps({
                        'content': f'Agent Engine failed: {exc}',
                        'type': 'failed',
                        'error_message': str(exc),
                    }, ensure_ascii=False)
                    yield f'event: engine\ndata: {error_data}\n\n'
            finally:
                if not segments_flushed and display_segments:
                    try:
                        flush_segments(last_engine_event)
                    except Exception:
                        logger.warning(
                            'failed to persist cached stream segments',
                            exc_info=True,
                        )
                if protocol_turn is not None and not protocol_finished:
                    try:
                        finish_agent_turn(
                            protocol_turn,
                            status=(
                                protocol_terminal_status
                                or AgentTurn.Status.INTERRUPTED
                            ),
                            items=(
                                protocol_projector.snapshot_items()
                                if protocol_projector is not None else []
                            ),
                            usage=(
                                last_engine_event.usage
                                if last_engine_event is not None else None
                            ),
                            error=protocol_terminal_error,
                        )
                    except Exception:
                        logger.warning(
                            'failed to persist agent protocol turn',
                            exc_info=True,
                        )
                if session is not None and acquired:
                    session.stream_lock.release()

        response = StreamingHttpResponse(
            event_stream(), content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Resume or steer an active adapter turn."""
        conversation = self.get_conversation(request, pk)
        serializer = ResumeAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = session_registry.get(str(conversation.id))
        if session is None:
            return Response(
                {'detail': 'No active agent session for this conversation.'},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            result = session.resume(
                text=serializer.validated_data['text'].strip(),
                selections=serializer.validated_data['selections'],
            )
            pending_request = AgentServerRequest.objects.filter(
                thread__conversation=conversation,
                status=AgentServerRequest.Status.PENDING,
            ).order_by('-created_at').first()
            if pending_request is not None:
                pending_request.status = AgentServerRequest.Status.RESOLVED
                pending_request.response = serializer.validated_data
                pending_request.resolved_at = timezone.now()
                pending_request.save(update_fields=[
                    'status', 'response', 'resolved_at',
                ])
            return Response({'status': result.value})
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

    @action(detail=True, methods=['post'], url_path='cancel-turn')
    def cancel_turn(self, request, pk=None):
        """Cancel the active turn; the open SSE response emits cancelled."""
        conversation = self.get_conversation(request, pk)
        session = session_registry.get(str(conversation.id))
        if session is None:
            return Response({'status': 'not_running'})
        try:
            result = session.cancel()
            return Response({'status': result.value})
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

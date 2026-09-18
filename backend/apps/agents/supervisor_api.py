from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_yasg.utils import swagger_auto_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.conversations.models import Conversation, Message
from apps.enterprise.models import Membership
from modules.catalog.errors import (
    DeploymentVersionConflict,
    DraftVersionConflict,
    InvalidDeploymentRevision,
    QualityGateNotPassed,
)
from modules.catalog.models import (
    AgentDeployment,
    AgentDraft,
    ApplicationDeployment,
)
from modules.catalog.services import publish_agent, switch_agent_deployment
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import (
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from modules.execution.application.start_runs import start_supervisor_run
from modules.tenancy.permissions import HasPathOrganization
from core.resource_access import (
    accessible_resources,
    can_administer_agents,
    can_create_agents,
    can_delete_agents,
    can_toggle_agents,
    can_update_agents,
    can_access_resource,
    is_platform_admin,
)

from .models import Agent, AgentCategory, SupervisorProfile


DEFAULT_LIMITS = {
    'max_tasks': 12,
    'max_replans': 3,
    'max_parallelism': 3,
    'timeout_seconds': 1800,
}


def _membership(request, organization_id):
    if request.user.is_superuser:
        return None
    return Membership.objects.filter(
        organization_id=organization_id,
        user=request.user,
        is_active=True,
    ).first()


def _can_edit(request, agent):
    return can_update_agents(request.user)


def _can_delete(request, agent):
    return can_delete_agents(request.user)


def _can_toggle(request, agent):
    return can_toggle_agents(request.user)


def _can_run(request, agent):
    if not agent.is_active:
        return False
    if not can_access_resource(agent, request.user):
        return False
    if is_platform_admin(request.user):
        return True
    membership = _membership(request, agent.organization_id)
    return bool(
        membership
        and membership.role in (
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
            Membership.Role.DEVELOPER,
            Membership.Role.OPERATOR,
        )
    )


def _visible_supervisors(request, organization_id):
    query = Agent.objects.filter(
        organization_id=organization_id,
        kind=Agent.Kind.SUPERVISOR,
    ).select_related('draft', 'supervisor_profile', 'category', 'created_by')
    if is_platform_admin(request.user):
        return query
    if not can_administer_agents(request.user):
        query = query.filter(is_active=True)
    return accessible_resources(query, request.user)


def validate_supervisor_team(agent, content, actor):
    config = content.get('orchestration_config') or {}
    agent_ids = {int(value) for value in config.get('agent_ids') or []}
    application_ids = {int(value) for value in config.get('application_ids') or []}
    if agent.id in agent_ids:
        raise serializers.ValidationError({'agent_ids': 'AI 分身不能调度自己。'})
    accessible_agents = accessible_resources(Agent.objects.filter(
        Q(organization=agent.organization) | Q(organization__isnull=True),
        id__in=agent_ids,
        kind=Agent.Kind.STANDARD,
        is_active=True,
    ), actor)
    if set(accessible_agents.values_list('id', flat=True)) != agent_ids:
        raise serializers.ValidationError({'agent_ids': '包含不可访问或非标准智能体。'})
    accessible_apps = accessible_resources(Application.objects.filter(
        Q(organization=agent.organization) | Q(organization__isnull=True),
        id__in=application_ids,
        is_active=True,
    ), actor)
    if set(accessible_apps.values_list('id', flat=True)) != application_ids:
        raise serializers.ValidationError({'application_ids': '包含不可访问的应用。'})
    missing_agents = agent_ids - set(AgentDeployment.objects.filter(
        agent_id__in=agent_ids,
    ).values_list('agent_id', flat=True))
    missing_apps = application_ids - set(ApplicationDeployment.objects.filter(
        application_id__in=application_ids,
    ).values_list('application_id', flat=True))
    if missing_agents or missing_apps:
        messages = []
        if missing_agents:
            agent_labels = [
                f'{name}（ID {agent_id}）'
                for agent_id, name in Agent.objects.filter(
                    id__in=missing_agents,
                ).order_by('id').values_list('id', 'name')
            ]
            messages.append(
                '以下智能体尚未部署：'
                f'{"、".join(agent_labels)}。请先在“企业管理 → 智能体发布”中激活版本'
            )
        if missing_apps:
            application_labels = [
                f'{name}（ID {application_id}）'
                for application_id, name in Application.objects.filter(
                    id__in=missing_apps,
                ).order_by('id').values_list('id', 'name')
            ]
            messages.append(
                '以下应用尚未部署：'
                f'{"、".join(application_labels)}。请先发布并部署应用'
            )
        raise serializers.ValidationError({'team': '；'.join(messages)})
    unsupported_apps = list(ApplicationDeployment.objects.filter(
        application_id__in=application_ids,
    ).select_related('revision').exclude(
        revision__content__executor_kind__in=('agent', 'media'),
    ).values_list('application_id', flat=True))
    if unsupported_apps:
        raise serializers.ValidationError({
            'application_ids': (
                'AI 分身首版只允许调度 Agent 或 Media 类型应用：'
                f'{sorted(unsupported_apps)}'
            )
        })


class SupervisorWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    slug = serializers.SlugField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)
    icon = serializers.CharField(required=False, allow_blank=True, max_length=50)
    visibility = serializers.ChoiceField(
        choices=SupervisorProfile.Visibility.choices,
        default=SupervisorProfile.Visibility.PRIVATE,
    )
    role_prompt = serializers.CharField()
    principles = serializers.ListField(
        child=serializers.CharField(max_length=500), required=False, default=list,
    )
    output_preferences = serializers.CharField(required=False, allow_blank=True)
    agent_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list,
    )
    application_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list,
    )
    model_config = serializers.JSONField(required=False, default=dict)
    limits = serializers.JSONField(required=False, default=dict)

    def validate_limits(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('limits 必须是对象。')
        limits = {**DEFAULT_LIMITS, **value}
        bounds = {
            'max_tasks': (1, 12),
            'max_replans': (0, 3),
            'max_parallelism': (1, 3),
            'timeout_seconds': (60, 1800),
        }
        for key, (minimum, maximum) in bounds.items():
            try:
                limits[key] = int(limits[key])
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError(f'{key} 必须是整数。') from exc
            if not minimum <= limits[key] <= maximum:
                raise serializers.ValidationError(
                    f'{key} 必须介于 {minimum} 和 {maximum} 之间。'
                )
        return limits

    def validate(self, attrs):
        attrs['agent_ids'] = list(dict.fromkeys(attrs.get('agent_ids') or []))
        attrs['application_ids'] = list(dict.fromkeys(attrs.get('application_ids') or []))
        if not attrs['agent_ids'] and not attrs['application_ids']:
            raise serializers.ValidationError('至少选择一个智能体或应用。')
        return attrs


class SupervisorReadSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    visibility = serializers.ChoiceField(choices=SupervisorProfile.Visibility.choices)
    role_prompt = serializers.CharField()
    principles = serializers.ListField(child=serializers.CharField())
    output_preferences = serializers.CharField()
    agent_ids = serializers.ListField(child=serializers.IntegerField())
    application_ids = serializers.ListField(child=serializers.IntegerField())
    model_config = serializers.JSONField()
    limits = serializers.JSONField()
    draft_version = serializers.IntegerField(allow_null=True)
    active_revision_id = serializers.UUIDField(allow_null=True)
    is_active = serializers.BooleanField()
    can_edit = serializers.BooleanField()
    can_delete = serializers.BooleanField()
    can_toggle = serializers.BooleanField()
    can_run = serializers.BooleanField()
    created_by_id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class SupervisorPublishSerializer(serializers.Serializer):
    expected_draft_version = serializers.IntegerField(required=False, min_value=1)
    release_notes = serializers.CharField(required=False, allow_blank=True)


class SupervisorDeploySerializer(serializers.Serializer):
    revision_id = serializers.UUIDField(required=False)
    expected_version = serializers.IntegerField(required=False, min_value=0)
    config_override = serializers.JSONField(required=False, default=dict)


class SupervisorRunStartSerializer(serializers.Serializer):
    goal = serializers.CharField()
    context = serializers.JSONField(required=False, default=dict)
    conversation_id = serializers.IntegerField(min_value=1)


def _definition(data):
    return {
        'system_prompt': data['role_prompt'],
        'model_config': data.get('model_config') or {},
        'tool_config': [],
        'knowledge_config': [],
        'guardrail_config': {},
        'workflow_config': {},
        'orchestration_config': {
            'principles': data.get('principles') or [],
            'output_preferences': data.get('output_preferences') or '',
            'agent_ids': data.get('agent_ids') or [],
            'application_ids': data.get('application_ids') or [],
            'limits': {**DEFAULT_LIMITS, **(data.get('limits') or {})},
        },
    }


def _serialize(agent, request):
    content = agent.draft.content if hasattr(agent, 'draft') else {}
    orchestration = content.get('orchestration_config') or {}
    deployment = AgentDeployment.objects.filter(
        agent=agent
    ).select_related('revision').first()
    return {
        'id': agent.id,
        'name': agent.name,
        'slug': agent.slug,
        'description': agent.description,
        'icon': agent.icon,
        'visibility': agent.supervisor_profile.visibility,
        'role_prompt': content.get('system_prompt', ''),
        'principles': orchestration.get('principles') or [],
        'output_preferences': orchestration.get('output_preferences', ''),
        'agent_ids': orchestration.get('agent_ids') or [],
        'application_ids': orchestration.get('application_ids') or [],
        'model_config': content.get('model_config') or {},
        'limits': {**DEFAULT_LIMITS, **(orchestration.get('limits') or {})},
        'draft_version': agent.draft.version if hasattr(agent, 'draft') else None,
        'active_revision_id': str(deployment.revision_id) if deployment else None,
        'is_active': agent.is_active,
        'can_edit': _can_edit(request, agent),
        'can_delete': _can_delete(request, agent),
        'can_toggle': _can_toggle(request, agent),
        'can_run': _can_run(request, agent),
        'created_by_id': agent.created_by_id,
        'created_at': agent.created_at,
        'updated_at': agent.updated_at,
    }


class SupervisorListCreateView(APIView):
    permission_classes = (HasPathOrganization,)

    @swagger_auto_schema(responses={200: SupervisorReadSerializer(many=True)})
    def get(self, request, organization_id):
        return Response([
            _serialize(item, request)
            for item in _visible_supervisors(request, organization_id)
        ])

    @swagger_auto_schema(
        request_body=SupervisorWriteSerializer,
        responses={201: SupervisorReadSerializer},
    )
    def post(self, request, organization_id):
        if not can_create_agents(request.user):
            return Response({'detail': '当前账号未获授权创建 AI 分身。'}, status=403)
        serializer = SupervisorWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if Agent.objects.filter(
            organization_id=organization_id,
            slug=data['slug'],
            is_active=True,
        ).exists():
            return Response({'slug': '当前组织中已存在该标识。'}, status=400)
        category, _ = AgentCategory.objects.get_or_create(
            slug='supervisor',
            defaults={
                'name': 'AI 分身',
                'description': '负责规划并调度其他智能体和应用',
                'icon': '🧭',
                'order': 5,
            },
        )
        with transaction.atomic():
            agent = Agent.objects.create(
                organization_id=organization_id,
                created_by=request.user,
                category=category,
                kind=Agent.Kind.SUPERVISOR,
                name=data['name'],
                slug=data['slug'],
                description=data.get('description', ''),
                icon=data.get('icon', '') or '🧭',
                is_public=False,
                access_scope=(
                    Agent.AccessScope.ORGANIZATION
                    if data['visibility'] == SupervisorProfile.Visibility.ORGANIZATION
                    else Agent.AccessScope.ADMIN
                ),
            )
            SupervisorProfile.objects.create(
                agent=agent, visibility=data['visibility'],
            )
            AgentDraft.objects.create(
                organization_id=organization_id,
                agent=agent,
                content=_definition(data),
                updated_by=request.user,
            )
        agent = Agent.objects.select_related(
            'draft', 'supervisor_profile', 'category', 'created_by',
        ).get(pk=agent.pk)
        return Response(_serialize(agent, request), status=status.HTTP_201_CREATED)


class SupervisorDetailView(APIView):
    permission_classes = (HasPathOrganization,)

    def _get(self, request, organization_id, delegate_id):
        return get_object_or_404(
            _visible_supervisors(request, organization_id), pk=delegate_id
        )

    @swagger_auto_schema(responses={200: SupervisorReadSerializer})
    def get(self, request, organization_id, delegate_id):
        return Response(_serialize(self._get(request, organization_id, delegate_id), request))

    @swagger_auto_schema(
        request_body=SupervisorWriteSerializer,
        responses={200: SupervisorReadSerializer},
    )
    def patch(self, request, organization_id, delegate_id):
        agent = self._get(request, organization_id, delegate_id)
        if not _can_edit(request, agent):
            return Response({'detail': '无权编辑该分身。'}, status=403)
        current = _serialize(agent, request)
        serializer = SupervisorWriteSerializer(data={**current, **request.data})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        duplicate = Agent.objects.filter(
            organization_id=organization_id,
            slug=data['slug'],
            is_active=True,
        ).exclude(pk=agent.pk).exists()
        if duplicate:
            return Response({'slug': '当前组织中已存在该标识。'}, status=400)
        with transaction.atomic():
            agent.name = data['name']
            agent.slug = data['slug']
            agent.description = data.get('description', '')
            agent.icon = data.get('icon', '') or '🧭'
            agent.save(update_fields=['name', 'slug', 'description', 'icon', 'updated_at'])
            profile = agent.supervisor_profile
            profile.visibility = data['visibility']
            profile.save(update_fields=['visibility', 'updated_at'])
            agent.access_scope = (
                Agent.AccessScope.ORGANIZATION
                if data['visibility'] == SupervisorProfile.Visibility.ORGANIZATION
                else Agent.AccessScope.ADMIN
            )
            agent.save(update_fields=['access_scope', 'updated_at'])
            agent.allowed_users.clear()
            draft = AgentDraft.objects.select_for_update().get(agent=agent)
            draft.content = _definition(data)
            draft.version += 1
            draft.updated_by = request.user
            draft.save(update_fields=['content', 'version', 'updated_by', 'updated_at'])
        agent.refresh_from_db()
        return Response(_serialize(agent, request))

    def delete(self, request, organization_id, delegate_id):
        agent = self._get(request, organization_id, delegate_id)
        if not _can_delete(request, agent):
            return Response({'detail': '无权删除该分身。'}, status=403)
        from modules.execution.models import Run
        if agent.revisions.exists() or Run.objects.filter(
            organization_id=organization_id,
            source_type='supervisor',
            source_id=str(agent.id),
        ).exists():
            agent.is_active = False
            agent.save(update_fields=['is_active', 'updated_at'])
        else:
            agent.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SupervisorPublishView(APIView):
    permission_classes = (HasPathOrganization,)

    @swagger_auto_schema(request_body=SupervisorPublishSerializer)
    def post(self, request, organization_id, delegate_id):
        agent = get_object_or_404(
            _visible_supervisors(request, organization_id), pk=delegate_id
        )
        if not _can_edit(request, agent):
            return Response({'detail': '无权发布该分身。'}, status=403)
        input_serializer = SupervisorPublishSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        draft = agent.draft
        validate_supervisor_team(agent, draft.content, request.user)
        try:
            revision = publish_agent(
                agent=agent,
                actor=request.user,
                expected_draft_version=int(
                    data.get('expected_draft_version', draft.version)
                ),
                release_notes=data.get('release_notes', ''),
            )
        except DraftVersionConflict as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response({
            'id': str(revision.id),
            'revision_no': revision.revision_no,
            'content_hash': revision.content_hash,
        }, status=201)


class SupervisorDeployView(APIView):
    permission_classes = (HasPathOrganization,)

    @swagger_auto_schema(request_body=SupervisorDeploySerializer)
    def post(self, request, organization_id, delegate_id):
        agent = get_object_or_404(
            _visible_supervisors(request, organization_id), pk=delegate_id
        )
        if not _can_toggle(request, agent):
            return Response({'detail': '无权部署该分身。'}, status=403)
        input_serializer = SupervisorDeploySerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        revision_id = data.get('revision_id')
        revision = agent.revisions.filter(pk=revision_id).first() if revision_id else (
            agent.revisions.order_by('-revision_no').first()
        )
        if revision is None:
            return Response({'detail': '请先发布分身版本。'}, status=409)
        validate_supervisor_team(agent, revision.content, request.user)
        current = AgentDeployment.objects.filter(agent=agent).first()
        try:
            deployment = switch_agent_deployment(
                agent=agent,
                actor=request.user,
                revision_id=revision.id,
                expected_version=int(data.get(
                    'expected_version', current.version if current else 0
                )),
                config_override=data.get('config_override') or {},
            )
        except (
            DeploymentVersionConflict,
            InvalidDeploymentRevision,
            QualityGateNotPassed,
        ) as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response({
            'id': str(deployment.id),
            'revision_id': str(deployment.revision_id),
            'version': deployment.version,
        })


class SupervisorStatusView(APIView):
    permission_classes = (HasPathOrganization,)

    def patch(self, request, organization_id, delegate_id):
        agent = get_object_or_404(
            Agent.objects.select_related(
                'draft', 'supervisor_profile', 'category', 'created_by',
            ),
            pk=delegate_id,
            organization_id=organization_id,
            kind=Agent.Kind.SUPERVISOR,
        )
        if not _can_toggle(request, agent):
            return Response({'detail': '无权启用或停用该分身。'}, status=403)
        if not can_access_resource(agent, request.user):
            return Response({'detail': '未找到可访问的分身。'}, status=404)
        if not isinstance(request.data.get('is_active'), bool):
            return Response({'is_active': '必须提供布尔值。'}, status=400)
        agent.is_active = request.data['is_active']
        agent.save(update_fields=['is_active', 'updated_at'])
        return Response(_serialize(agent, request))


class SupervisorRunView(APIView):
    permission_classes = (HasPathOrganization,)

    @swagger_auto_schema(
        request_body=SupervisorRunStartSerializer,
        responses={202: RunSerializer},
    )
    def post(self, request, organization_id, delegate_id):
        agent = get_object_or_404(
            _visible_supervisors(request, organization_id), pk=delegate_id
        )
        if not _can_run(request, agent):
            return Response({'detail': '无权运行该分身。'}, status=403)
        input_serializer = SupervisorRunStartSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        goal = data['goal'].strip()
        key = (request.headers.get('Idempotency-Key') or '').strip()
        if not key or len(key) > 160:
            return Response({'detail': '请提供有效的 Idempotency-Key。'}, status=400)
        conversation_id = data['conversation_id']
        conversation = Conversation.objects.filter(
            pk=conversation_id,
            organization_id=organization_id,
            user=request.user,
            agent=agent,
        ).first()
        if conversation is None:
            return Response(
                {'conversation_id': '请选择该分身所属的有效任务会话。'}, status=400
            )
        try:
            run, replayed = start_supervisor_run(
                organization_id=organization_id,
                supervisor_id=agent.id,
                actor=request.user,
                goal=goal,
                context=data.get('context') or {},
                conversation_id=conversation.id,
                idempotency_key=key,
            )
        except IdempotencyKeyReused as exc:
            return Response({'detail': str(exc)}, status=409)
        except DeploymentUnavailable as exc:
            return Response({'detail': str(exc)}, status=409)
        except InvalidExecutionDefinition as exc:
            return Response({'detail': str(exc)}, status=422)
        Message.objects.get_or_create(
            conversation=conversation,
            run=run,
            role='user',
            run_event_sequence=None,
            defaults={
                'content': goal,
                'metadata': {'run_id': str(run.id), 'supervisor': True},
            },
        )
        response = Response(RunSerializer(run).data, status=202)
        if replayed:
            response['Idempotent-Replay'] = 'true'
        return response

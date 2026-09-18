from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.db.models.deletion import ProtectedError
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.utils import swagger_auto_schema
from .models import AgentCategory, Agent
from modules.catalog.errors import (
    DeploymentRollbackUnavailable, DeploymentVersionConflict,
    InvalidDeploymentRevision, QualityGateNotPassed,
)
from modules.catalog.models import (
    AgentDeployment, AgentDraft, AgentRevision,
)
from modules.catalog.services import (
    publish_agent, rollback_agent_deployment, switch_agent_deployment,
)
from .serializers import (
    AgentCategorySerializer,
    AgentListSerializer,
    AgentDetailSerializer,
    ExecuteAgentSerializer, AgentWriteSerializer, AgentDeploymentSerializer,
    AgentRevisionSerializer,
)
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import (
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from modules.execution.application.start_runs import start_agent_run
from modules.execution.models import Run
from .filters import AgentFilter
from core.permissions import (
    CanCreateAgent,
    CanDeleteAgent,
    CanToggleAgent,
    CanUpdateAgent,
    IsAdmin,
)
from core.resource_access import (
    ResourcePermissionSerializer,
    accessible_resources,
    can_create_agents,
    can_manage_resource_permissions,
    is_platform_admin,
    can_administer_agents,
    can_delete_agents,
    can_toggle_agents,
    can_update_agents,
)

class AgentCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AgentCategory.objects.all()
    serializer_class = AgentCategorySerializer
    permission_classes = [IsAuthenticated]

class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.filter(
        is_public=True, is_active=True, kind=Agent.Kind.STANDARD,
    ).select_related('category')
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'description']
    filterset_class = AgentFilter

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return AgentWriteSerializer
        if self.action == 'retrieve':
            return AgentDetailSerializer
        return AgentListSerializer

    def get_permissions(self):
        if self.action == 'permissions':
            return [IsAuthenticated()]
        if self.action == 'create':
            return [CanCreateAgent()]
        if self.action in ('update', 'partial_update') or (
            self.action == 'versions' and self.request.method == 'POST'
        ):
            return [CanUpdateAgent()]
        if self.action == 'destroy':
            return [CanDeleteAgent()]
        if self.action in ('deploy', 'rollback', 'status'):
            return [CanToggleAgent()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = Agent.objects.filter(kind=Agent.Kind.STANDARD).select_related(
            'category', 'created_by', 'draft'
        )
        manageable_list = (
            self.action == 'list'
            and self.request.query_params.get('manageable') == '1'
            and can_administer_agents(self.request.user)
        )
        if self.action not in ('status', 'destroy') and not manageable_list:
            queryset = queryset.filter(is_active=True)
        from apps.enterprise.models import Membership
        queryset = queryset.annotate(current_user_org_role=Subquery(
            Membership.objects.filter(
                organization_id=OuterRef('organization_id'),
                user=self.request.user,
                is_active=True,
            ).values('role')[:1]
        ))
        action_capability = {
            'update': can_update_agents,
            'partial_update': can_update_agents,
            'destroy': can_delete_agents,
            'deploy': can_toggle_agents,
            'rollback': can_toggle_agents,
            'status': can_toggle_agents,
        }.get(self.action)
        can_read_lifecycle = self.action in ('deployment', 'versions') and (
            can_update_agents(self.request.user)
            or can_toggle_agents(self.request.user)
        )
        if manageable_list or can_read_lifecycle or (
            action_capability and action_capability(self.request.user)
        ):
            if self.action == 'list':
                from apps.enterprise.permissions import resolve_organization
                queryset = queryset.filter(
                    organization=resolve_organization(self.request),
                )
            if is_platform_admin(self.request.user):
                return queryset
            return accessible_resources(queryset, self.request.user)
        queryset = accessible_resources(queryset, self.request.user)
        if self.request.query_params.get('mine') == '1':
            from apps.enterprise.permissions import resolve_organization
            return queryset.filter(organization=resolve_organization(self.request))
        return queryset

    @swagger_auto_schema(
        method='get', responses={200: ResourcePermissionSerializer()},
    )
    @swagger_auto_schema(
        method='put', request_body=ResourcePermissionSerializer,
        responses={200: ResourcePermissionSerializer()},
    )
    @action(detail=True, methods=['get', 'put'], url_path='permissions')
    def permissions(self, request, pk=None):
        agent = self.get_object()
        if not can_manage_resource_permissions(agent, request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('无权管理该智能体的访问权限。')
        if request.method == 'GET':
            return Response(ResourcePermissionSerializer(
                agent, context={'request': request}).data)
        serializer = ResourcePermissionSerializer(
            agent, data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def perform_create(self, serializer):
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(self.request)
        membership = getattr(self.request, 'organization_membership', None)
        if not organization or not membership:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('需要有效的组织成员资格才能创建智能体。')
        if not can_create_agents(self.request.user, organization):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('需要组织开发者或更高角色才能创建智能体。')
        with transaction.atomic():
            agent = serializer.save(
                created_by=self.request.user,
                organization=organization,
                kind=Agent.Kind.STANDARD,
            )
            draft = AgentDraft.objects.get(agent=agent)
            publish_agent(
                agent=agent,
                actor=self.request.user,
                expected_draft_version=draft.version,
                release_notes='Initial version 1.0.0',
            )

    def perform_update(self, serializer):
        self.require_agent_capability(
            self.request, serializer.instance, can_update_agents,
            '无权修改该组织的智能体。',
        )
        serializer.save()

    def perform_destroy(self, instance):
        self.require_agent_capability(
            self.request, instance, can_delete_agents,
            '无权删除该组织的智能体。',
        )
        from modules.catalog.models import (
            ApplicationDeployment,
            ApplicationDraft,
        )

        def references_agent(definition):
            return str(instance.id) in {
                str(binding.get('agent_id'))
                for binding in (definition or {}).get('agent_bindings', [])
            }

        with transaction.atomic():
            locked = Agent.objects.select_for_update().get(pk=instance.pk)
            definitions = list(ApplicationDraft.objects.filter(
                organization=locked.organization,
            ).values_list('content', flat=True))
            deployments = list(ApplicationDeployment.objects.filter(
                organization=locked.organization,
            ).select_related('revision', 'previous_revision'))
            definitions += [deployment.revision.content for deployment in deployments]
            if any(references_agent(definition) for definition in definitions):
                raise ProtectedError(
                    'Agent is referenced by an active application definition.',
                    [locked],
                )

            # An old revision remains an immutable audit snapshot, but it must
            # no longer be offered as a rollback target after its Agent is gone.
            stale_rollback_ids = [
                deployment.id
                for deployment in deployments
                if deployment.previous_revision is not None
                and references_agent(deployment.previous_revision.content)
            ]
            if stale_rollback_ids:
                ApplicationDeployment.objects.filter(
                    id__in=stale_rollback_ids,
                ).update(previous_revision=None)
            if locked.revisions.exists():
                locked.is_active = False
                locked.save(update_fields=['is_active', 'updated_at'])
            else:
                locked.delete()

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': '该智能体正在被应用引用，无法删除。'},
                status=status.HTTP_409_CONFLICT,
            )

    def require_agent_capability(self, request, agent, capability, message):
        if not capability(request.user, agent):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(message)

    @action(detail=True, methods=['get'])
    def deployment(self, request, pk=None):
        agent = self.get_object()
        self.require_agent_capability(
            request,
            agent,
            lambda user, resource: (
                can_update_agents(user, resource)
                or can_toggle_agents(user, resource)
            ),
            '无权查看该智能体的部署信息。',
        )
        deployment = AgentDeployment.objects.filter(agent=agent).first()
        return Response(
            AgentDeploymentSerializer(deployment).data if deployment else None
        )

    @action(detail=True, methods=['get', 'post'])
    def versions(self, request, pk=None):
        agent = self.get_object()
        self.require_agent_capability(
            request,
            agent,
            lambda user, resource: (
                can_update_agents(user, resource)
                or can_toggle_agents(user, resource)
            ),
            '无权查看该智能体的版本。',
        )
        if request.method == 'GET':
            return Response(AgentRevisionSerializer(
                agent.revisions.order_by('-revision_no'), many=True).data)

        self.require_agent_capability(
            request, agent, can_update_agents, '无权修改该智能体。',
        )
        draft = AgentDraft.objects.filter(agent=agent).first()
        if draft is None:
            return Response({'detail': 'Agent draft is missing.'}, status=409)
        reserved = {'expected_draft_version', 'release_notes', 'content'}
        supplied = request.data.get('content')
        if supplied is None:
            supplied = {
                key: value for key, value in request.data.items()
                if key not in reserved
            }
        if supplied:
            if not isinstance(supplied, dict):
                return Response({'content': 'Must be a JSON object.'}, status=400)
            draft.content = {**draft.content, **supplied}
            draft.version += 1
            draft.updated_by = request.user
            draft.save(update_fields=[
                'content', 'version', 'updated_by', 'updated_at',
            ])
        revision = publish_agent(
            agent=agent,
            actor=request.user,
            expected_draft_version=draft.version,
            release_notes=request.data.get('release_notes', ''),
        )
        return Response(AgentRevisionSerializer(revision).data, status=201)

    @action(detail=True, methods=['post'])
    def deploy(self, request, pk=None):
        agent = self.get_object()
        self.require_agent_capability(
            request, agent, can_toggle_agents, '无权启用该智能体版本。',
        )
        revision_id = request.data.get('revision_id') or request.data.get('version_id')
        if not revision_id:
            revision_id = AgentRevision.objects.filter(
                agent=agent).order_by('-revision_no').values_list('id', flat=True).first()
        if not revision_id:
            return Response({'detail': 'Publish an Agent revision first.'}, status=409)
        current = AgentDeployment.objects.filter(
            agent=agent).first()
        expected_version = request.data.get(
            'expected_version', current.version if current else 0)
        try:
            deployment = switch_agent_deployment(
                agent=agent,
                actor=request.user,
                revision_id=revision_id,
                expected_version=int(expected_version),
                config_override=(request.data.get('config_override')
                                 or request.data.get('config_overrides') or {}),
            )
        except (DeploymentVersionConflict, InvalidDeploymentRevision,
                QualityGateNotPassed) as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response(AgentDeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def rollback(self, request, pk=None):
        agent = self.get_object()
        self.require_agent_capability(
            request, agent, can_toggle_agents, '无权切换该智能体版本。',
        )
        current = AgentDeployment.objects.filter(
            agent=agent).first()
        expected_version = request.data.get(
            'expected_version', current.version if current else 0)
        try:
            deployment = rollback_agent_deployment(
                agent=agent,
                actor=request.user,
                expected_version=int(expected_version),
            )
        except (DeploymentRollbackUnavailable, DeploymentVersionConflict) as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response(AgentDeploymentSerializer(deployment).data)

    @action(detail=True, methods=['patch'], url_path='status')
    def status(self, request, pk=None):
        agent = self.get_object()
        self.require_agent_capability(
            request, agent, can_toggle_agents, '无权启用或停用该智能体。',
        )
        if not isinstance(request.data.get('is_active'), bool):
            return Response(
                {'is_active': '必须提供布尔值。'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        agent.is_active = request.data['is_active']
        agent.save(update_fields=['is_active', 'updated_at'])
        return Response(AgentListSerializer(agent, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def execute(self, request, pk=None):
        agent = self.get_object()
        from apps.enterprise.models import Membership
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request)
        if organization is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('An active organization membership is required.')
        membership = getattr(request, 'organization_membership', None)
        if (
            not request.user.is_superuser
            and (
                membership is None
                or membership.organization_id != organization.id
                or membership.role not in (
                    Membership.Role.OWNER,
                    Membership.Role.ADMIN,
                    Membership.Role.OPERATOR,
                    Membership.Role.DEVELOPER,
                )
            )
        ):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Operator role is required to execute an agent.')
        serializer = ExecuteAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = (request.headers.get('Idempotency-Key') or '').strip()
        if not idempotency_key or len(idempotency_key) > 160:
            return Response(
                {'detail': 'Idempotency-Key must contain between 1 and 160 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            run, replayed = start_agent_run(
                organization_id=organization.id,
                agent_id=agent.id,
                actor=request.user,
                input_data=serializer.validated_data['input_data'],
                idempotency_key=idempotency_key,
            )
        except IdempotencyKeyReused as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except DeploymentUnavailable as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidExecutionDefinition as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        response = Response(RunSerializer(run).data, status=status.HTTP_202_ACCEPTED)
        if replayed:
            response['Idempotent-Replay'] = 'true'
        return response

    @action(detail=False, methods=['get'])
    def my_executions(self, request):
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request)
        runs = Run.objects.filter(
            organization=organization,
            owner=request.user,
            executor_kind=Run.ExecutorKind.AGENT,
        ).order_by('-created_at')[:20]
        return Response(RunSerializer(runs, many=True).data)

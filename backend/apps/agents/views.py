from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import OuterRef, Q, Subquery
from django.db.models.deletion import ProtectedError
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from .models import AgentCategory, Agent
from modules.catalog.errors import (
    DeploymentRollbackUnavailable, DeploymentVersionConflict,
    InvalidDeploymentRevision, QualityGateNotPassed,
)
from modules.catalog.models import (
    AgentDeployment, AgentDraft, AgentRevision, DeploymentEnvironment,
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

class AgentCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AgentCategory.objects.all()
    serializer_class = AgentCategorySerializer
    permission_classes = [AllowAny]

class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.filter(is_public=True).select_related('category')
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
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = Agent.objects.select_related('category', 'created_by', 'draft')
        if not self.request.user.is_authenticated:
            return queryset.filter(is_public=True)
        from apps.enterprise.models import Membership
        queryset = queryset.annotate(current_user_org_role=Subquery(
            Membership.objects.filter(
                organization_id=OuterRef('organization_id'),
                user=self.request.user,
                is_active=True,
            ).values('role')[:1]
        ))
        if self.request.query_params.get('mine') == '1':
            from apps.enterprise.permissions import resolve_organization
            return queryset.filter(organization=resolve_organization(self.request))
        org_ids = self.request.user.organization_memberships.filter(
            is_active=True).values_list('organization_id', flat=True)
        return queryset.filter(Q(is_public=True) | Q(organization_id__in=org_ids)).distinct()

    def perform_create(self, serializer):
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(self.request)
        from apps.enterprise.models import Membership
        membership = getattr(self.request, 'organization_membership', None)
        if not organization or not membership or membership.role not in (
                Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.DEVELOPER):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Developer role is required to create an agent.')
        serializer.save(created_by=self.request.user, organization=organization)

    def perform_update(self, serializer):
        from apps.enterprise.models import Membership
        self.require_agent_role(self.request, serializer.instance, (
            Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.DEVELOPER))
        serializer.save()

    def perform_destroy(self, instance):
        from apps.enterprise.models import Membership
        self.require_agent_role(self.request, instance, (
            Membership.Role.OWNER, Membership.Role.ADMIN))
        from modules.catalog.models import ApplicationDraft, ApplicationRevision
        definitions = list(ApplicationDraft.objects.filter(
            organization=instance.organization).values_list('content', flat=True))
        definitions += list(ApplicationRevision.objects.filter(
            organization=instance.organization).values_list('content', flat=True))
        if any(str(instance.id) in {
            str(binding.get('agent_id'))
            for binding in definition.get('agent_bindings', [])
        } for definition in definitions):
            raise ProtectedError('Agent is referenced by an application definition.', [instance])
        instance.delete()

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': '该智能体正在被应用引用，无法删除。'},
                status=status.HTTP_409_CONFLICT,
            )

    def require_agent_role(self, request, agent, roles):
        from apps.enterprise.models import Membership
        if request.user.is_superuser:
            return
        membership = Membership.objects.filter(
            organization=agent.organization, user=request.user,
            is_active=True, role__in=roles).first()
        if membership is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Insufficient role in the agent organization.')

    @action(detail=True, methods=['get'])
    def deployments(self, request, pk=None):
        agent = self.get_object()
        from apps.enterprise.models import Membership
        self.require_agent_role(request, agent, tuple(dict(Membership.Role.choices)))
        return Response(AgentDeploymentSerializer(agent.deployments.all(), many=True).data)

    @action(detail=True, methods=['get', 'post'])
    def versions(self, request, pk=None):
        agent = self.get_object()
        from apps.enterprise.models import Membership
        self.require_agent_role(request, agent, (
            Membership.Role.OWNER, Membership.Role.ADMIN,
            Membership.Role.DEVELOPER, Membership.Role.OPERATOR,
            Membership.Role.AUDITOR, Membership.Role.VIEWER,
        ))
        if request.method == 'GET':
            return Response(AgentRevisionSerializer(
                agent.revisions.order_by('-revision_no'), many=True).data)

        self.require_agent_role(request, agent, (
            Membership.Role.OWNER, Membership.Role.ADMIN,
            Membership.Role.DEVELOPER,
        ))
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
        from apps.enterprise.models import Membership
        self.require_agent_role(request, agent, (
            Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.OPERATOR))
        environment = request.data.get('environment', 'development')
        if environment not in dict(DeploymentEnvironment.choices):
            return Response({'environment': 'Invalid deployment environment.'}, status=400)
        if environment == DeploymentEnvironment.PRODUCTION:
            self.require_agent_role(request, agent, (
                Membership.Role.OWNER, Membership.Role.ADMIN,
            ))
        revision_id = request.data.get('revision_id') or request.data.get('version_id')
        if not revision_id:
            revision_id = AgentRevision.objects.filter(
                agent=agent).order_by('-revision_no').values_list('id', flat=True).first()
        if not revision_id:
            return Response({'detail': 'Publish an Agent revision first.'}, status=409)
        current = AgentDeployment.objects.filter(
            agent=agent, environment=environment).first()
        expected_version = request.data.get(
            'expected_version', current.version if current else 0)
        try:
            deployment = switch_agent_deployment(
                agent=agent,
                actor=request.user,
                environment=environment,
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
        from apps.enterprise.models import Membership
        self.require_agent_role(request, agent, (
            Membership.Role.OWNER, Membership.Role.ADMIN,
            Membership.Role.OPERATOR,
        ))
        environment = request.data.get('environment', 'development')
        if environment == DeploymentEnvironment.PRODUCTION:
            self.require_agent_role(request, agent, (
                Membership.Role.OWNER, Membership.Role.ADMIN,
            ))
        current = AgentDeployment.objects.filter(
            agent=agent, environment=environment).first()
        expected_version = request.data.get(
            'expected_version', current.version if current else 0)
        try:
            deployment = rollback_agent_deployment(
                agent=agent,
                actor=request.user,
                environment=environment,
                expected_version=int(expected_version),
            )
        except (DeploymentRollbackUnavailable, DeploymentVersionConflict) as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response(AgentDeploymentSerializer(deployment).data)

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
                environment=request.data.get('environment', 'production'),
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

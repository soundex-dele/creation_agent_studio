from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AuditLog, AutomationTrigger, Connector, EvaluationCase, EvaluationRun,
    EvaluationSuite, GovernancePolicy, IdentityProvider, Membership, Organization,
    ProviderConfig, QuotaPolicy, RunTrace, SecretReference, UsageRecord,
)
from .permissions import OrganizationRolePermission, resolve_organization
from .serializers import (
    AuditLogSerializer, AutomationTriggerSerializer, ConnectorSerializer,
    EvaluationCaseSerializer, EvaluationRunSerializer, EvaluationSuiteSerializer,
    GovernancePolicySerializer, IdentityProviderSerializer, MembershipSerializer,
    OrganizationSerializer, ProviderConfigSerializer, QuotaPolicySerializer,
    RunTraceSerializer, SecretReferenceSerializer, UsageRecordSerializer,
)
from .services import dispatch_automation, start_evaluation
from .tenancy import (
    get_single_tenant_organization,
    provision_single_tenant_user,
    single_tenant_mode_enabled,
)


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def _require_admin(self, organization):
        membership = organization.memberships.filter(
            user=self.request.user, is_active=True).first()
        if not membership or membership.role not in (
                Membership.Role.OWNER, Membership.Role.ADMIN):
            raise PermissionDenied('Administrator role required.')

    def get_queryset(self):
        if single_tenant_mode_enabled():
            membership = provision_single_tenant_user(self.request.user)
            return Organization.objects.filter(
                pk=membership.organization_id) if membership else Organization.objects.none()
        return Organization.objects.filter(
            memberships__user=self.request.user,
            memberships__is_active=True,
        ).distinct()

    @transaction.atomic
    def perform_create(self, serializer):
        if single_tenant_mode_enabled():
            raise MethodNotAllowed(
                'POST', detail='Organization creation is disabled in single-tenant mode.')
        organization = serializer.save(owner=self.request.user)
        Membership.objects.create(organization=organization, user=self.request.user,
                                  role=Membership.Role.OWNER)
        QuotaPolicy.objects.create(organization=organization)
        GovernancePolicy.objects.create(organization=organization)

    def perform_destroy(self, instance):
        if single_tenant_mode_enabled():
            raise MethodNotAllowed(
                'DELETE', detail='The deployment organization cannot be deleted.')
        if instance.owner_id != self.request.user.id:
            raise PermissionDenied('Only the owner may delete an organization.')
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

    def perform_update(self, serializer):
        self._require_admin(serializer.instance)
        serializer.save()

    @action(detail=True, methods=['get', 'post'], url_path='members')
    def members(self, request, pk=None):
        organization = self.get_object()
        membership = organization.memberships.filter(
            user=request.user, is_active=True).first()
        if request.method == 'GET':
            return Response(MembershipSerializer(
                organization.memberships.select_related('user'), many=True).data)
        if not membership or membership.role not in (
                Membership.Role.OWNER, Membership.Role.ADMIN):
            return Response({'detail': 'Administrator role required.'}, status=403)
        serializer = MembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_user_model().objects.get(id=serializer.validated_data.pop('user_id'))
        member, _ = Membership.objects.update_or_create(
            organization=organization, user=user,
            defaults=serializer.validated_data)
        return Response(MembershipSerializer(member).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path=r'members/(?P<member_id>[^/.]+)')
    def member_detail(self, request, pk=None, member_id=None):
        organization = self.get_object()
        actor = organization.memberships.filter(
            user=request.user, is_active=True).first()
        if not actor or actor.role not in (Membership.Role.OWNER, Membership.Role.ADMIN):
            return Response({'detail': 'Administrator role required.'}, status=403)
        member = organization.memberships.filter(id=member_id).first()
        if member is None:
            return Response({'detail': 'Member not found.'}, status=404)
        if member.role == Membership.Role.OWNER:
            return Response({'detail': 'Organization owner cannot be removed here.'}, status=409)
        if request.method == 'DELETE':
            member.is_active = False
            member.save(update_fields=['is_active', 'updated_at'])
            return Response(status=204)
        serializer = MembershipSerializer(member, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DeploymentContextView(APIView):
    """Return the server-controlled tenancy mode and visible workspaces."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        single_tenant = single_tenant_mode_enabled()
        if single_tenant:
            membership = provision_single_tenant_user(request.user)
            organizations = [membership.organization] if membership else []
        else:
            organizations = list(
                Organization.objects.visible_to(request.user)
                .filter(is_active=True)
                .order_by('created_at')
            )
        return Response({
            'single_tenant_mode': single_tenant,
            'organizations': OrganizationSerializer(
                organizations, many=True, context={'request': request}).data,
        })


class TenantModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]

    def get_organization(self):
        return resolve_organization(self.request)

    def get_queryset(self):
        return self.queryset.filter(organization=self.get_organization())

    def perform_create(self, serializer):
        serializer.save(organization=self.get_organization())


class ProviderConfigViewSet(TenantModelViewSet):
    queryset = ProviderConfig.objects.order_by('name')
    serializer_class = ProviderConfigSerializer


class SecretReferenceViewSet(TenantModelViewSet):
    queryset = SecretReference.objects.all()
    serializer_class = SecretReferenceSerializer
    minimum_role = Membership.Role.ADMIN


class IdentityProviderViewSet(TenantModelViewSet):
    queryset = IdentityProvider.objects.all()
    serializer_class = IdentityProviderSerializer
    minimum_role = Membership.Role.ADMIN

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def discovery(self, request):
        organization = self.get_organization()
        providers = self.get_queryset().filter(is_active=True)
        return Response([{
            'id': str(provider.id), 'name': provider.name,
            'protocol': provider.protocol, 'issuer': provider.issuer,
            'metadata_url': provider.metadata_url,
            'enforce_sso': provider.enforce_sso,
        } for provider in providers])


class PublicIdentityDiscoveryView(APIView):
    permission_classes = []

    def get(self, request):
        domain = str(request.query_params.get('domain') or '').lower().strip()
        if not domain:
            return Response({'domain': 'This field is required.'}, status=400)
        providers = IdentityProvider.objects.filter(
            protocol=IdentityProvider.Protocol.OIDC, is_active=True,
            organization__is_active=True)
        if single_tenant_mode_enabled():
            organization = get_single_tenant_organization()
            providers = providers.filter(
                organization=organization) if organization else providers.none()
        values = [{
            'id': provider.id, 'name': provider.name,
            'organization': provider.organization.name,
            'login_url': request.build_absolute_uri(
                f'/api/v1/enterprise/sso/oidc/{provider.id}/login'),
        } for provider in providers if domain in {
            str(value).lower() for value in provider.domains}]
        return Response(values)


class GovernancePolicyViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]
    minimum_write_role = Membership.Role.ADMIN

    def list(self, request):
        policy, _ = GovernancePolicy.objects.get_or_create(
            organization=resolve_organization(request))
        return Response(GovernancePolicySerializer(policy).data)

    def partial_update(self, request, pk=None):
        policy, _ = GovernancePolicy.objects.get_or_create(
            organization=resolve_organization(request))
        serializer = GovernancePolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ConnectorViewSet(TenantModelViewSet):
    queryset = Connector.objects.all()
    serializer_class = ConnectorSerializer

    @action(detail=True, methods=['post'])
    def invoke(self, request, pk=None):
        from .services import invoke_connector
        connector = self.get_object()
        try:
            result = invoke_connector(
                connector, request.data if isinstance(request.data, dict) else {})
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        except RuntimeError as exc:
            return Response({'detail': str(exc)}, status=502)
        return Response(result)


class AutomationTriggerViewSet(TenantModelViewSet):
    queryset = AutomationTrigger.objects.all()
    serializer_class = AutomationTriggerSerializer

    @action(detail=True, methods=['post'])
    def trigger(self, request, pk=None):
        trigger = self.get_object()
        trace = dispatch_automation(
            trigger, request.user,
            request.data if isinstance(request.data, dict) else {})
        return Response(RunTraceSerializer(trace).data, status=202)


class EvaluationSuiteViewSet(TenantModelViewSet):
    queryset = EvaluationSuite.objects.all()
    serializer_class = EvaluationSuiteSerializer

    @action(detail=True, methods=['get', 'post'])
    def cases(self, request, pk=None):
        suite = self.get_object()
        if request.method == 'GET':
            return Response(EvaluationCaseSerializer(suite.cases.all(), many=True).data)
        serializer = EvaluationCaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        case = serializer.save(suite=suite)
        return Response(EvaluationCaseSerializer(case).data, status=201)

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        suite = self.get_object()
        try:
            run = start_evaluation(
                suite,
                request.user,
                target_version=str(request.data.get('target_version') or ''),
                environment=str(request.data.get('environment') or 'staging'),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=422)
        return Response(EvaluationRunSerializer(run).data, status=202)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, OrganizationRolePermission]

    def get_queryset(self):
        organization = resolve_organization(self.request)
        queryset = AuditLog.objects.filter(organization=organization).select_related('actor')
        action_name = self.request.query_params.get('action')
        return queryset.filter(action=action_name) if action_name else queryset


class RunTraceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RunTraceSerializer
    permission_classes = [IsAuthenticated, OrganizationRolePermission]

    def get_queryset(self):
        return RunTrace.objects.filter(
            organization=resolve_organization(self.request)).prefetch_related('spans')


class UsageViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UsageRecordSerializer
    permission_classes = [IsAuthenticated, OrganizationRolePermission]

    def get_queryset(self):
        return UsageRecord.objects.filter(organization=resolve_organization(self.request))

    @action(detail=False, methods=['get'])
    def summary(self, request):
        organization = resolve_organization(request)
        now = timezone.now()
        records = self.get_queryset().filter(created_at__year=now.year,
                                             created_at__month=now.month)
        totals = records.aggregate(tokens=Sum('total_tokens'), cost=Sum('cost'))
        quota, _ = QuotaPolicy.objects.get_or_create(organization=organization)
        return Response({
            'tokens': totals['tokens'] or 0,
            'cost': totals['cost'] or 0,
            'monthly_token_limit': quota.monthly_token_limit,
            'monthly_cost_limit': quota.monthly_cost_limit,
        })


class QuotaViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]
    minimum_write_role = Membership.Role.ADMIN

    def list(self, request):
        quota, _ = QuotaPolicy.objects.get_or_create(
            organization=resolve_organization(request))
        return Response(QuotaPolicySerializer(quota).data)

    def partial_update(self, request, pk=None):
        quota, _ = QuotaPolicy.objects.get_or_create(
            organization=resolve_organization(request))
        serializer = QuotaPolicySerializer(quota, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ScimUsersView(APIView):
    """Minimal SCIM 2.0 Users surface scoped to an organization admin."""
    permission_classes = [IsAuthenticated, OrganizationRolePermission]
    minimum_role = Membership.Role.ADMIN

    def get(self, request):
        organization = resolve_organization(request)
        memberships = organization.memberships.select_related('user').filter(is_active=True)
        resources = [{
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
            'id': str(member.user_id), 'userName': member.user.username,
            'active': member.is_active,
            'emails': [{'value': member.user.email, 'primary': True}],
            'roles': [{'value': member.role}],
        } for member in memberships]
        return Response({'schemas': ['urn:ietf:params:scim:api:messages:2.0:ListResponse'],
                         'totalResults': len(resources), 'Resources': resources})

    def post(self, request):
        organization = resolve_organization(request)
        username = request.data.get('userName')
        email = ((request.data.get('emails') or [{}])[0]).get('value', '')
        if not username:
            return Response({'detail': 'userName is required.'}, status=400)
        user, created = get_user_model().objects.get_or_create(
            username=username, defaults={'email': email, 'is_active': True})
        if created:
            user.set_unusable_password()
            user.save(update_fields=['password'])
        role = (((request.data.get('roles') or [{}])[0]).get('value') or
                Membership.Role.VIEWER)
        if role not in dict(Membership.Role.choices) or role == Membership.Role.OWNER:
            role = Membership.Role.VIEWER
        member, _ = Membership.objects.update_or_create(
            organization=organization, user=user,
            defaults={'role': role,
                      'is_active': bool(request.data.get('active', True))})
        return Response({'id': str(user.id), 'userName': user.username,
                         'active': member.is_active}, status=201 if created else 200)


class ScimUserDetailView(APIView):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]
    minimum_role = Membership.Role.ADMIN

    def _membership(self, request, user_id):
        return resolve_organization(request).memberships.select_related('user').filter(
            user_id=user_id).first()

    @staticmethod
    def _serialize(member):
        return {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
            'id': str(member.user_id), 'userName': member.user.username,
            'active': member.is_active,
            'emails': [{'value': member.user.email, 'primary': True}],
            'roles': [{'value': member.role}],
        }

    def get(self, request, user_id):
        member = self._membership(request, user_id)
        return Response(self._serialize(member)) if member else Response(status=404)

    def patch(self, request, user_id):
        member = self._membership(request, user_id)
        if not member:
            return Response(status=404)
        if member.role == Membership.Role.OWNER:
            return Response({'detail': 'Organization owner cannot be changed by SCIM.'}, status=409)
        data = dict(request.data)
        for operation in request.data.get('Operations', []):
            if str(operation.get('op', '')).lower() in ('replace', 'add'):
                path = str(operation.get('path') or '')
                if path:
                    data[path] = operation.get('value')
                elif isinstance(operation.get('value'), dict):
                    data.update(operation['value'])
        if 'active' in data:
            member.is_active = bool(data['active'])
        roles = data.get('roles')
        if roles:
            role = roles[0] if isinstance(roles[0], str) else roles[0].get('value')
            if role in dict(Membership.Role.choices) and role != Membership.Role.OWNER:
                member.role = role
        emails = data.get('emails')
        if emails:
            member.user.email = emails[0] if isinstance(emails[0], str) else emails[0].get('value', '')
            member.user.save(update_fields=['email'])
        member.save(update_fields=['is_active', 'role', 'updated_at'])
        return Response(self._serialize(member))

    def delete(self, request, user_id):
        member = self._membership(request, user_id)
        if not member:
            return Response(status=404)
        if member.role == Membership.Role.OWNER:
            return Response({'detail': 'Organization owner cannot be removed by SCIM.'}, status=409)
        member.is_active = False
        member.save(update_fields=['is_active', 'updated_at'])
        return Response(status=204)

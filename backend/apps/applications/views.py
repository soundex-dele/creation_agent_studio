from django.db import transaction
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.utils import swagger_auto_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.enterprise.models import Membership
from apps.enterprise.permissions import OrganizationRolePermission, resolve_organization
from modules.catalog.models import SkillDraft
from .filters import ApplicationFilter
from .models import (
    Application, ApplicationCategory, Skill,
)
from .serializers import (
    ApplicationCategorySerializer, ApplicationDetailSerializer,
    ApplicationListSerializer,
    ComposeGuidedPromptSerializer, SkillSerializer,
)
from .services import compose_guided_prompt
from .serializers import application_definition
from core.resource_access import (
    ResourcePermissionSerializer,
    accessible_resources,
    bulk_update_resource_permissions,
    can_manage_resource_permissions,
)


def _runtime_prefetch(queryset):
    return queryset.select_related('category').select_related('draft')


class ApplicationCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ApplicationCategory.objects.all()
    serializer_class = ApplicationCategorySerializer
    permission_classes = [IsAuthenticated]


class ApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only discovery surface; Catalog owns all Application writes."""
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'description']
    filterset_class = ApplicationFilter
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = _runtime_prefetch(Application.objects.all())
        if getattr(self.request, 'remote_connector', False):
            queryset = queryset.filter(
                Q(organization_id=self.request.remote_organization_id) | Q(organization__isnull=True))
        if self.action != 'permissions':
            queryset = queryset.filter(is_active=True)
        return accessible_resources(queryset, self.request.user)

    def get_permissions(self):
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ApplicationDetailSerializer
        return ApplicationListSerializer

    @swagger_auto_schema(
        method='get', responses={200: ResourcePermissionSerializer()},
    )
    @swagger_auto_schema(
        method='put', request_body=ResourcePermissionSerializer,
        responses={200: ResourcePermissionSerializer()},
    )
    @action(detail=True, methods=['get', 'put'], url_path='permissions')
    def permissions(self, request, *args, **kwargs):
        application = self.get_object()
        if not can_manage_resource_permissions(application, request.user):
            raise PermissionDenied('无权管理该应用的访问权限。')
        if request.method == 'GET':
            return Response(ResourcePermissionSerializer(
                application, context={'request': request}).data)
        serializer = ResourcePermissionSerializer(
            application, data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['put'], url_path='bulk-permissions')
    def bulk_permissions(self, request, *args, **kwargs):
        updated = bulk_update_resource_permissions(
            Application.objects.filter(
                organization=resolve_organization(request),
            ),
            request,
            request.data,
        )
        return Response({'updated': updated})

    @action(detail=True, methods=['post'], url_path='compose-prompt')
    def compose_prompt(self, request, *args, **kwargs):
        application = self.get_object()
        serializer = ComposeGuidedPromptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prompts = application_definition(application).get('guided_prompts', [])
        prompt_id = str(serializer.validated_data['prompt_id'])
        prompt = next((item for item in prompts if str(item.get('id') or item.get('key')) == prompt_id), None)
        if prompt is None:
            return Response({'detail': '引导问题不存在。'}, status=404)
        return Response(compose_guided_prompt(
            prompt, serializer.validated_data['answers'],
            application_id=application.id))


class SkillViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]
    serializer_class = SkillSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        organization = resolve_organization(self.request, required=False)
        return Skill.objects.filter(
            Q(organization=organization) | Q(visibility=Skill.Visibility.PUBLIC)
        )

    @transaction.atomic
    def perform_create(self, serializer):
        organization = resolve_organization(self.request)
        skill = serializer.save(
            owner=self.request.user,
            organization=organization,
        )
        SkillDraft.objects.create(
            organization=organization,
            skill=skill,
            updated_by=self.request.user,
            content={
                "source_type": skill.source_type,
                "source_uri": skill.source_uri,
                "artifact_key": skill.artifact_key,
                "manifest": skill.manifest,
                "content_hash": skill.content_hash,
            },
        )

    @transaction.atomic
    def perform_update(self, serializer):
        skill = serializer.instance
        membership = getattr(self.request, 'organization_membership', None)
        if (
            not self.request.user.is_superuser
            and not (
                membership
                and membership.organization_id == skill.organization_id
                and membership.role in (
                    Membership.Role.OWNER,
                    Membership.Role.ADMIN,
                    Membership.Role.DEVELOPER,
                )
            )
        ):
            raise PermissionDenied('无权修改该 Skill。')
        definition_fields = {
            key: value
            for key, value in serializer.validated_data.items()
            if key in {
                "source_type", "source_uri", "artifact_key", "manifest", "content_hash"
            }
        }
        skill = serializer.save()
        if definition_fields and skill.organization_id is not None:
            draft = SkillDraft.objects.select_for_update().get(skill=skill)
            draft.content = {**draft.content, **definition_fields}
            draft.version += 1
            draft.updated_by = self.request.user
            draft.save(
                update_fields=("content", "version", "updated_by", "updated_at")
            )

    def perform_destroy(self, instance):
        membership = getattr(self.request, 'organization_membership', None)
        if (
            not self.request.user.is_superuser
            and not (
                membership
                and membership.organization_id == instance.organization_id
                and membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
            )
        ):
            raise PermissionDenied('无权删除该 Skill。')
        instance.delete()

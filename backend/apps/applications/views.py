from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.enterprise.models import Membership
from apps.enterprise.permissions import OrganizationRolePermission, resolve_organization
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


def _runtime_prefetch(queryset):
    return queryset.select_related('category').select_related('draft')


class ApplicationCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ApplicationCategory.objects.all()
    serializer_class = ApplicationCategorySerializer
    permission_classes = [AllowAny]


class ApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only discovery surface; Catalog owns all Application writes."""
    permission_classes = [AllowAny]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'description']
    filterset_class = ApplicationFilter
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = _runtime_prefetch(Application.objects.all())
        if self.request.user.is_authenticated:
            organization = resolve_organization(self.request, required=False)
            return queryset.filter(
                Q(is_public=True) | Q(created_by=self.request.user) |
                Q(organization=organization))
        return queryset.filter(is_public=True)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ApplicationDetailSerializer
        return ApplicationListSerializer

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
                Q(owner=self.request.user) | Q(organization=organization) |
                Q(visibility=Skill.Visibility.PUBLIC))

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user,
                        organization=resolve_organization(
                            self.request, required=False))

    def perform_update(self, serializer):
        skill = serializer.instance
        membership = getattr(self.request, 'organization_membership', None)
        if (
            skill.owner_id != self.request.user.id
            and not self.request.user.is_superuser
            and not (
                membership
                and membership.organization_id == skill.organization_id
                and membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
            )
        ):
            raise PermissionDenied('无权修改该 Skill。')
        serializer.save()

    def perform_destroy(self, instance):
        membership = getattr(self.request, 'organization_membership', None)
        if (
            instance.owner_id != self.request.user.id
            and not self.request.user.is_superuser
            and not (
                membership
                and membership.organization_id == instance.organization_id
                and membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
            )
        ):
            raise PermissionDenied('无权删除该 Skill。')
        instance.delete()

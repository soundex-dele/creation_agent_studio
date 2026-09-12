from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.enterprise.permissions import resolve_organization
from core.llm.factory import build_image_provider
from .filters import ApplicationFilter
from .models import (
    Application, ApplicationCategory, Skill,
)
from .serializers import (
    ApplicationCategorySerializer, ApplicationDetailSerializer,
    ApplicationListSerializer, ApplicationWriteSerializer,
    ComposeGuidedPromptSerializer, GenerateImageSerializer, SkillSerializer,
)
from .services import compose_guided_prompt
from .serializers import application_definition


def _runtime_prefetch(queryset):
    return queryset.select_related('category').select_related('draft')


class ApplicationCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ApplicationCategory.objects.all()
    serializer_class = ApplicationCategorySerializer
    permission_classes = [AllowAny]


class ApplicationViewSet(viewsets.ModelViewSet):
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'description']
    filterset_class = ApplicationFilter
    lookup_field = 'slug'

    def get_permissions(self):
        return ([AllowAny()] if self.action in ('list', 'retrieve')
                else [IsAuthenticated()])

    def get_queryset(self):
        queryset = _runtime_prefetch(Application.objects.all())
        if self.request.user.is_authenticated:
            organization = resolve_organization(self.request, required=False)
            return queryset.filter(
                Q(is_public=True) | Q(created_by=self.request.user) |
                Q(organization=organization))
        return queryset.filter(is_public=True)

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ApplicationWriteSerializer
        if self.action == 'retrieve':
            return ApplicationDetailSerializer
        return ApplicationListSerializer

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            organization=resolve_organization(self.request, required=False))

    def perform_update(self, serializer):
        if (serializer.instance.created_by_id != self.request.user.id
                and not self.request.user.is_superuser):
            raise PermissionDenied('只有应用所有者可以编辑。')
        serializer.save()

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
    permission_classes = [IsAuthenticated]
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
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_image(request):
    serializer = GenerateImageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    provider = build_image_provider()
    if provider is None:
        return Response(
            {'detail': '图片生成服务未配置，请在后端 .env 设置 IMAGE_API_KEY。'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE)
    kwargs = {}
    if serializer.validated_data.get('size'):
        kwargs['size'] = serializer.validated_data['size']
    result = provider.generate(serializer.validated_data['prompt'], **kwargs)
    if not result.success:
        return Response({'detail': result.error or '图片生成失败。'},
                        status=status.HTTP_502_BAD_GATEWAY)
    image_url = result.url or (
        f'data:image/png;base64,{result.base64}' if result.base64 else '')
    return Response({'success': True, 'image_url': image_url,
                     'revised_prompt': result.revised_prompt})

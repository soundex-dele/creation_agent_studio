from django.db.models import Count, F
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsOwnerOrReadOnly
from .filters import TemplateFilter
from .models import Template, TemplateCategory
from .access import visible_cases
from apps.enterprise.permissions import resolve_organization
from .serializers import (
    CreateTemplateSerializer,
    TemplateCategorySerializer,
    TemplateDetailSerializer,
    TemplateListSerializer,
    UpdateTemplateSerializer,
)


class TemplateCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TemplateCategory.objects.all()
    serializer_class = TemplateCategorySerializer
    permission_classes = [AllowAny]


class TemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = [
        'title', 'summary', 'source_title', 'source_author', 'source_platform',
        'recommended_reason',
    ]
    filterset_class = TemplateFilter

    def get_queryset(self):
        organization = resolve_organization(self.request)
        return visible_cases(self.request.user, organization.pk if organization else None).select_related(
            'category', 'created_by').prefetch_related('analysis_sections').annotate(
            analysis_count=Count('analysis_sections', distinct=True)
        ).order_by(
            '-is_featured', '-updated_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return TemplateListSerializer
        if self.action == 'retrieve':
            return TemplateDetailSerializer
        if self.action == 'create':
            return CreateTemplateSerializer
        return UpdateTemplateSerializer

    def perform_create(self, serializer):
        from apps.enterprise.permissions import resolve_organization
        serializer.save(
            created_by=self.request.user,
            organization=resolve_organization(self.request),
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        Template.objects.filter(pk=instance.pk).update(view_count=F('view_count') + 1)
        instance.view_count += 1
        return Response(TemplateDetailSerializer(instance, context={'request': request}).data)

    @action(detail=False, methods=['get'])
    def douyin_applications(self, request):
        from apps.applications.models import Application
        from core.resource_access import accessible_resources
        organization = resolve_organization(request)
        targets = accessible_resources(Application.objects.for_organization(
            organization.pk if organization else None).filter(
                slug='douyin-benchmark', kind='custom', is_active=True), request.user, operation='run')
        return Response([{'id': row.pk, 'name': row.name} for row in targets.order_by('id')])

    @action(detail=False, methods=['get'])
    def my_templates(self, request):
        templates = self.get_queryset().filter(created_by=request.user)
        return Response(TemplateListSerializer(templates, many=True, context={'request': request}).data)

    @action(detail=False, methods=['get'])
    def featured(self, request):
        templates = self.get_queryset().filter(
            status='published', is_featured=True)[:12]
        return Response(TemplateListSerializer(templates, many=True).data)

from rest_framework import serializers

from .models import Template, TemplateAnalysisSection, TemplateCategory


class TemplateCategorySerializer(serializers.ModelSerializer):
    template_count = serializers.SerializerMethodField()

    class Meta:
        model = TemplateCategory
        fields = ['id', 'name', 'slug', 'description', 'order', 'template_count']

    def get_template_count(self, obj):
        return obj.templates.filter(status='published').count()


class TemplateAnalysisSectionSerializer(serializers.ModelSerializer):
    section_type_display = serializers.CharField(
        source='get_section_type_display', read_only=True)

    class Meta:
        model = TemplateAnalysisSection
        fields = [
            'id', 'section_type', 'section_type_display', 'title', 'content',
            'evidence_quote', 'order', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TemplateListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True)
    content_type_display = serializers.CharField(
        source='get_content_type_display', read_only=True)
    analysis_count = serializers.SerializerMethodField()

    def get_analysis_count(self, obj):
        annotated = getattr(obj, 'analysis_count', None)
        return annotated if annotated is not None else obj.analysis_sections.count()

    class Meta:
        model = Template
        fields = [
            'id', 'title', 'summary', 'thumbnail', 'tags', 'category_name',
            'content_type', 'content_type_display', 'source_author',
            'source_platform', 'source_published_at', 'recommended_reason',
            'word_count', 'reading_time_minutes', 'analysis_count',
            'is_featured', 'view_count', 'created_by_username', 'created_at',
            'updated_at',
            'status', 'source_kind',
        ]


class TemplateDetailSerializer(serializers.ModelSerializer):
    source_navigation = serializers.SerializerMethodField()

    def get_source_navigation(self, obj):
        request = self.context.get('request')
        if obj.source_kind != 'douyin' or not request or request.user.pk != obj.created_by_id:
            return None
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request)
        if not organization or organization.pk != obj.organization_id:
            return {'available': False}
        from app_center.douyin_benchmark.backend.cases import source_navigation
        return source_navigation(obj, request.user)

    category = TemplateCategorySerializer(read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True)
    content_type_display = serializers.CharField(
        source='get_content_type_display', read_only=True)
    copyright_mode_display = serializers.CharField(
        source='get_copyright_mode_display', read_only=True)
    analysis_sections = TemplateAnalysisSectionSerializer(many=True, read_only=True)

    class Meta:
        model = Template
        fields = [
            'id', 'title', 'summary', 'thumbnail', 'tags', 'category',
            'content_type', 'content_type_display', 'source_title', 'source_url',
            'source_author', 'source_platform', 'source_published_at',
            'source_excerpt', 'source_content', 'recommended_reason',
            'reusable_patterns', 'copyright_mode', 'copyright_mode_display',
            'source_snapshot_at', 'word_count', 'reading_time_minutes',
            'analysis_sections', 'status', 'is_featured', 'view_count',
            'created_by_username', 'created_at', 'updated_at',
            'source_kind', 'source_navigation',
        ]


class _TemplateWriteSerializer(serializers.ModelSerializer):
    analysis_sections = TemplateAnalysisSectionSerializer(many=True, required=False)

    class Meta:
        model = Template
        fields = [
            'category', 'title', 'summary', 'thumbnail', 'tags', 'content_type',
            'source_title', 'source_url', 'source_author', 'source_platform',
            'source_published_at', 'source_excerpt', 'source_content',
            'recommended_reason', 'reusable_patterns', 'copyright_mode',
            'source_snapshot_at', 'word_count', 'reading_time_minutes',
            'analysis_sections', 'status', 'is_featured',
        ]

    @staticmethod
    def _replace_analysis(template, sections):
        template.analysis_sections.all().delete()
        TemplateAnalysisSection.objects.bulk_create([
            TemplateAnalysisSection(template=template, **section)
            for section in sections
        ])

    def create(self, validated_data):
        sections = validated_data.pop('analysis_sections', [])
        template = super().create(validated_data)
        self._replace_analysis(template, sections)
        return template

    def update(self, instance, validated_data):
        sections = validated_data.pop('analysis_sections', None)
        template = super().update(instance, validated_data)
        if sections is not None:
            self._replace_analysis(template, sections)
        return template


class CreateTemplateSerializer(_TemplateWriteSerializer):
    pass


class UpdateTemplateSerializer(_TemplateWriteSerializer):
    pass

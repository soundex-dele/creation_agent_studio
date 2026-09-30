from rest_framework import serializers
from django.db.models import Q

from apps.applications.models import Application
from core.resource_access import accessible_resources
from apps.projects.services.workspace_paths import application_working_directory
from .models import Project, ProjectAsset

class ProjectAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectAsset
        fields = ['id', 'asset_type', 'name', 'url', 'file', 'content', 'metadata', 'order', 'created_at']

class ProjectListSerializer(serializers.ModelSerializer):
    application_slug = serializers.CharField(
        source='application.slug', read_only=True, allow_null=True)
    application_kind = serializers.CharField(
        source='application.kind', read_only=True, allow_null=True)
    conversation_id = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    def get_conversation_id(self, obj):
        # Standalone application history must identify the exact conversation
        # it opens. Workflow-step conversations are restored through their run.
        conversation = next(iter(obj.conversations.all()), None)
        return conversation.id if conversation else None

    def get_source(self, obj):
        if obj.workflow_id:
            return 'workflow'
        if obj.application_id:
            return 'application'
        # Projects created by application runs before the explicit FK was
        # introduced have no application_id. Preserve their historical
        # classification until they are lazily associated on the next run.
        return 'application'

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'status', 'thumbnail', 'scope', 'directory_source',
            'application_id', 'application_slug', 'application_kind', 'conversation_id',
            'workflow_id', 'working_directory', 'source', 'created_at', 'updated_at',
        ]
        read_only_fields = ['application_id', 'working_directory', 'scope', 'directory_source']

class ProjectDetailSerializer(serializers.ModelSerializer):
    application_slug = serializers.CharField(
        source='application.slug', read_only=True, allow_null=True)
    assets = ProjectAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'structure', 'status', 'thumbnail', 'scope', 'directory_source',
            'application_id', 'application_slug',
            'workflow_id', 'working_directory', 'assets', 'created_at', 'updated_at',
        ]
        read_only_fields = ['application_id', 'working_directory', 'scope', 'directory_source']

class CreateProjectSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(required=False, write_only=True)
    working_directory = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)

    class Meta:
        model = Project
        fields = ['title', 'description', 'application_id', 'scope', 'working_directory']

    def validate(self, attrs):
        if attrs.get('scope', 'default') == 'cowork':
            if not attrs.get('working_directory', '').strip():
                raise serializers.ValidationError({'working_directory': '请选择项目文件夹。'})
            if attrs.get('application_id'):
                raise serializers.ValidationError({'application_id': 'CoWork 项目不能绑定其他应用。'})
        elif attrs.get('working_directory') or not attrs.get('title', '').strip():
            raise serializers.ValidationError('普通项目需要名称并使用自动分配的目录。')
        return attrs

    def validate_application_id(self, value):
        request = self.context['request']
        organization = getattr(request, 'organization', None)
        application = accessible_resources(
            Application.objects.filter(
                Q(organization=organization) | Q(organization__isnull=True),
                id=value,
                is_active=True,
            ),
            request.user,
        ).first()
        if application is None:
            raise serializers.ValidationError('应用不存在或无权访问。')
        return value

    def create(self, validated_data):
        if validated_data.get('scope') == 'cowork':
            from .services.cowork import bind_directory
            return bind_directory(self.context['request'].user,
                self.context['request'].organization,
                validated_data['working_directory'], validated_data.get('title', ''))
        validated_data.pop('working_directory', None)
        application_id = validated_data.pop('application_id', None)
        project = Project.objects.create(
            user=self.context['request'].user,
            organization=self.context['request'].organization,
            application_id=application_id,
            **validated_data
        )
        application_working_directory(project)
        return project

from rest_framework import serializers
from django.db.models import Q

from apps.applications.models import Application
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
            'id', 'title', 'description', 'status', 'thumbnail',
            'application_id', 'application_slug', 'application_kind', 'conversation_id',
            'workflow_id', 'working_directory', 'source', 'created_at', 'updated_at',
        ]
        read_only_fields = ['application_id', 'working_directory']

class ProjectDetailSerializer(serializers.ModelSerializer):
    application_slug = serializers.CharField(
        source='application.slug', read_only=True, allow_null=True)
    assets = ProjectAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'structure', 'status', 'thumbnail',
            'application_id', 'application_slug',
            'workflow_id', 'working_directory', 'assets', 'created_at', 'updated_at',
        ]
        read_only_fields = ['application_id', 'working_directory']

class CreateProjectSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(required=False, write_only=True)

    class Meta:
        model = Project
        fields = ['title', 'description', 'application_id']

    def validate_application_id(self, value):
        request = self.context['request']
        organization = getattr(request, 'organization', None)
        application = Application.objects.filter(id=value).filter(
            Q(is_public=True) | Q(organization=organization) |
            Q(created_by=request.user)
        ).first()
        if application is None:
            raise serializers.ValidationError('应用不存在或无权访问。')
        return value

    def create(self, validated_data):
        application_id = validated_data.pop('application_id', None)
        project = Project.objects.create(
            user=self.context['request'].user,
            organization=getattr(self.context['request'], 'organization', None),
            application_id=application_id,
            **validated_data
        )
        application_working_directory(project)
        return project

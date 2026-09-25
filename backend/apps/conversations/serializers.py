"""
Serializers for conversations app.
"""
from django.db.models import Q
from rest_framework import serializers
from apps.agents.models import Agent
from apps.projects.services.workspace_paths import validate_system_working_directory
from core.agent_engine.tool_display import normalize_tool_metadata
from modules.execution.api.serializers import RunSerializer
from modules.execution.models import Run
from .models import Conversation, Message, MessageAttachment


MAX_MESSAGE_IMAGES = 4
MAX_MESSAGE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {
    'JPEG': 'image/jpeg',
    'PNG': 'image/png',
    'WEBP': 'image/webp',
}


class MessageAttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = MessageAttachment
        fields = [
            'id', 'url', 'original_name', 'content_type', 'byte_size',
            'width', 'height', 'created_at',
        ]

    def get_url(self, obj):
        if not obj.file:
            return ''
        url = f"/{obj.file.url.lstrip('/')}"
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class MessageSerializer(serializers.ModelSerializer):
    """消息序列化器"""
    attachments = MessageAttachmentSerializer(many=True, read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['metadata'] = normalize_tool_metadata(data.get('metadata'))
        return data

    class Meta:
        model = Message
        fields = [
            'id', 'run_id', 'role', 'content', 'metadata', 'attachments',
            'created_at',
        ]


class AgentNestedSerializer(serializers.ModelSerializer):
    """对话所属智能体的轻量序列化器（前端空状态展示用）"""

    class Meta:
        model = Agent
        fields = ['id', 'name', 'icon', 'description']


class ConversationListSerializer(serializers.ModelSerializer):
    """对话列表序列化器"""
    last_message = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()
    agent = AgentNestedSerializer(read_only=True)
    project = serializers.IntegerField(source='project_id', read_only=True)
    application_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Conversation
        fields = ['id', 'organization_id', 'title', 'agent', 'project', 'process_id',
                  'agent_locked',
                  'application_id',
                  'working_directory',
                  'created_at', 'updated_at',
                  'last_message', 'message_count']

    def get_last_message(self, obj):
        last_message = obj.messages.last()
        if last_message:
            return MessageSerializer(last_message).data
        return None

    def get_message_count(self, obj):
        return obj.messages.count()


class ConversationDetailSerializer(serializers.ModelSerializer):
    """对话详情序列化器"""
    messages = MessageSerializer(many=True, read_only=True)
    agent = AgentNestedSerializer(read_only=True)
    project = serializers.IntegerField(source='project_id', read_only=True)
    application_id = serializers.IntegerField(read_only=True)
    skills = serializers.SerializerMethodField()
    active_run = serializers.SerializerMethodField()
    latest_run = serializers.SerializerMethodField()
    organization_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Conversation
        fields = ['id', 'organization_id', 'title', 'agent', 'project', 'process_id',
                  'agent_locked',
                  'application_id',
                  'working_directory',
                  'skills', 'created_at', 'updated_at',
                  'messages', 'active_run', 'latest_run']

    def get_skills(self, obj):
        return [{
            'id': str(binding.skill_id),
            'slug': binding.skill.slug,
            'name': binding.skill.name,
            'source': binding.source,
            'enabled': binding.enabled,
        } for binding in obj.skill_bindings.select_related('skill').all()]

    def _related_runs(self, obj):
        return Run.objects.for_organization(obj.organization_id).filter(
            Q(source_type='conversation', source_id=str(obj.id))
            | Q(
                source_type='supervisor',
                definition_snapshot__conversation_id=str(obj.id),
            )
            | Q(
                source_type='workflow_step',
                definition_snapshot__conversation_id=str(obj.id),
            )
            | Q(
                source_type='supervisor_task',
                definition_snapshot__conversation_id=str(obj.id),
            )
        ).select_related('current_attempt').order_by('-created_at')

    def get_active_run(self, obj):
        run = self._related_runs(obj).filter(
            status__in=(
                Run.Status.QUEUED,
                Run.Status.RUNNING,
                Run.Status.WAITING_INPUT,
                Run.Status.WAITING_CHILDREN,
                Run.Status.CANCELLING,
            ),
        ).first()
        return RunSerializer(run).data if run else None

    def get_latest_run(self, obj):
        run = self._related_runs(obj).first()
        return RunSerializer(run).data if run else None


class CreateConversationSerializer(serializers.Serializer):
    """创建对话序列化器"""
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    agent_id = serializers.IntegerField(required=False)
    project_id = serializers.IntegerField(required=False)
    process_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    application_id = serializers.IntegerField(required=False)
    working_directory = serializers.CharField(
        required=False, allow_blank=True, max_length=1000)
    skill_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list)

    def validate_working_directory(self, value):
        if not value.strip():
            return ''
        try:
            return validate_system_working_directory(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class SendMessageSerializer(serializers.Serializer):
    """发送消息序列化器"""
    content = serializers.CharField(
        required=False, allow_blank=True, default='', trim_whitespace=False)
    images = serializers.ListField(
        child=serializers.ImageField(allow_empty_file=False),
        required=False,
        default=list,
        max_length=MAX_MESSAGE_IMAGES,
        write_only=True,
    )
    conversation_id = serializers.IntegerField(required=False)
    permission_mode = serializers.ChoiceField(
        choices=('default', 'allow_all'), required=False, default='default')
    collaboration_mode = serializers.ChoiceField(
        choices=('default', 'plan'), required=False, default='default')
    agent_id = serializers.IntegerField(required=False, allow_null=True)
    skill_names = serializers.ListField(
        child=serializers.CharField(max_length=160), required=False, default=list)

    def validate_images(self, images):
        for image in images:
            if image.size > MAX_MESSAGE_IMAGE_BYTES:
                raise serializers.ValidationError('每张图片不能超过 10MB。')
            image_format = str(getattr(getattr(image, 'image', None), 'format', '')).upper()
            detected_type = ALLOWED_IMAGE_FORMATS.get(image_format)
            if detected_type is None:
                raise serializers.ValidationError('仅支持 JPG、PNG 和 WebP 图片。')
            declared_type = str(getattr(image, 'content_type', '') or '').lower()
            if declared_type == 'image/jpg':
                declared_type = 'image/jpeg'
            if (
                declared_type not in ('', 'application/octet-stream')
                and declared_type != detected_type
            ):
                raise serializers.ValidationError('图片内容与文件类型不匹配。')
            image.content_type = detected_type
        return images

    def validate(self, attrs):
        if not str(attrs.get('content') or '').strip() and not attrs.get('images'):
            raise serializers.ValidationError('请输入消息或选择至少一张图片。')
        return attrs

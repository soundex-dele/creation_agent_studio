"""
Serializers for conversations app.
"""
from rest_framework import serializers
from apps.agents.models import Agent
from apps.projects.services.workspace_paths import validate_system_working_directory
from .models import (
    AgentItem,
    AgentServerRequest,
    AgentThread,
    AgentTurn,
    Conversation,
    Message,
)


class MessageSerializer(serializers.ModelSerializer):
    """消息序列化器"""

    class Meta:
        model = Message
        fields = ['id', 'role', 'content', 'metadata', 'created_at']


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
    chat_application_id = serializers.IntegerField(read_only=True)
    workflow_step_run_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'agent', 'project', 'process_id',
                  'application_id', 'chat_application_id', 'workflow_step_run_id',
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
    chat_application_id = serializers.IntegerField(read_only=True)
    workflow_step_run_id = serializers.UUIDField(read_only=True)
    skills = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'agent', 'project', 'process_id',
                  'application_id', 'chat_application_id', 'workflow_step_run_id',
                  'working_directory',
                  'skills', 'created_at', 'updated_at',
                  'messages']

    def get_skills(self, obj):
        return [{
            'id': str(binding.skill_id),
            'slug': binding.skill.slug,
            'name': binding.skill.name,
            'source': binding.source,
            'enabled': binding.enabled,
        } for binding in obj.skill_bindings.select_related('skill').all()]


class CreateConversationSerializer(serializers.Serializer):
    """创建对话序列化器"""
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    agent_id = serializers.IntegerField(required=False)
    project_id = serializers.IntegerField(required=False)
    process_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    application_id = serializers.IntegerField(required=False)
    workflow_step_run_id = serializers.UUIDField(required=False)
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
    content = serializers.CharField(required=True)
    conversation_id = serializers.IntegerField(required=False)


class StreamMessageSerializer(serializers.Serializer):
    """流式消息请求序列化器"""
    message = serializers.CharField(required=True)
    protocol_version = serializers.ChoiceField(
        choices=[1, 2], required=False, default=1
    )
    permission_mode = serializers.ChoiceField(
        choices=['default', 'allow_all'], required=False, default='default'
    )
    skills = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        default=list,
    )
    agent_id = serializers.IntegerField(required=False, allow_null=True)


class ResumeAgentSerializer(serializers.Serializer):
    """Answer, resume, or steer the active agent adapter turn."""
    text = serializers.CharField(required=False, allow_blank=True, default='')
    selections = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True, default=list
    )

    def validate(self, attrs):
        if not attrs.get('text', '').strip() and not attrs.get('selections'):
            raise serializers.ValidationError('Provide text or at least one selection.')
        return attrs


class AgentItemProtocolSerializer(serializers.ModelSerializer):
    localId = serializers.UUIDField(source='id', read_only=True)
    id = serializers.CharField(source='remote_id', read_only=True)
    type = serializers.CharField(source='item_type', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = AgentItem
        fields = [
            'id', 'localId', 'type', 'status', 'ordinal', 'content', 'payload',
            'createdAt', 'updatedAt',
        ]


class AgentTurnProtocolSerializer(serializers.ModelSerializer):
    remoteId = serializers.CharField(source='remote_id', read_only=True)
    threadId = serializers.UUIDField(source='thread_id', read_only=True)
    status = serializers.SerializerMethodField()
    items = AgentItemProtocolSerializer(many=True, read_only=True)
    startedAt = serializers.DateTimeField(source='started_at', read_only=True)
    completedAt = serializers.DateTimeField(
        source='completed_at', read_only=True)

    class Meta:
        model = AgentTurn
        fields = [
            'id', 'remoteId', 'threadId', 'status', 'input', 'usage', 'error',
            'items', 'startedAt', 'completedAt',
        ]

    def get_status(self, obj):
        return {
            AgentTurn.Status.IN_PROGRESS: 'inProgress',
        }.get(obj.status, obj.status)


class AgentThreadProtocolSerializer(serializers.ModelSerializer):
    remoteId = serializers.CharField(source='remote_id', read_only=True)
    conversationId = serializers.IntegerField(
        source='conversation_id', read_only=True)
    turns = AgentTurnProtocolSerializer(many=True, read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = AgentThread
        fields = [
            'id', 'remoteId', 'conversationId', 'provider', 'status', 'config',
            'turns', 'createdAt', 'updatedAt',
        ]


class AgentServerRequestProtocolSerializer(serializers.ModelSerializer):
    requestId = serializers.CharField(source='remote_id', read_only=True)
    threadId = serializers.UUIDField(source='thread_id', read_only=True)
    turnId = serializers.UUIDField(source='turn_id', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    resolvedAt = serializers.DateTimeField(source='resolved_at', read_only=True)

    class Meta:
        model = AgentServerRequest
        fields = [
            'id', 'requestId', 'threadId', 'turnId', 'method', 'params',
            'status', 'response', 'createdAt', 'resolvedAt',
        ]

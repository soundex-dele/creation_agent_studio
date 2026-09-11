"""
Serializers for conversations app.
"""
from rest_framework import serializers
from apps.agents.models import Agent
from apps.projects.services.workspace_paths import validate_system_working_directory
from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    """消息序列化器"""

    class Meta:
        model = Message
        fields = ['id', 'run_id', 'role', 'content', 'metadata', 'created_at']


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
        fields = ['id', 'title', 'agent', 'project', 'process_id',
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

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'agent', 'project', 'process_id',
                  'application_id',
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

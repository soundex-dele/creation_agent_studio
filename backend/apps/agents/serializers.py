from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from .models import Agent, AgentCategory
from modules.catalog.models import AgentDeployment, AgentDraft, AgentRevision


def _agent_permissions(agent, request):
    if not request or not request.user.is_authenticated:
        return False, False
    if request.user.is_superuser:
        return True, True
    from apps.enterprise.models import Membership
    role = getattr(agent, 'current_user_org_role', None)
    if role is None:
        role = Membership.objects.filter(
            organization=agent.organization,
            user=request.user,
            is_active=True,
        ).values_list('role', flat=True).first()
    if role is None:
        return False, False
    can_edit = role in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.DEVELOPER,
    )
    can_delete = role in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    )
    return can_edit, can_delete


class AgentCategorySerializer(serializers.ModelSerializer):
    agent_count = serializers.SerializerMethodField()

    class Meta:
        model = AgentCategory
        fields = ['id', 'name', 'slug', 'description', 'icon', 'order', 'agent_count']

    def get_agent_count(self, obj):
        return obj.agents.filter(is_public=True).count()


class AgentListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = ['id', 'name', 'slug', 'description', 'icon', 'category_name',
                  'is_public', 'can_edit', 'can_delete', 'created_at']

    def get_can_edit(self, obj):
        return _agent_permissions(obj, self.context.get('request'))[0]

    def get_can_delete(self, obj):
        return _agent_permissions(obj, self.context.get('request'))[1]


class AgentDetailSerializer(serializers.ModelSerializer):
    category = AgentCategorySerializer(read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True)
    skill_bindings = serializers.SerializerMethodField()
    system_prompt = serializers.SerializerMethodField()
    model_config = serializers.SerializerMethodField()
    tool_config = serializers.SerializerMethodField()
    knowledge_config = serializers.SerializerMethodField()
    guardrail_config = serializers.SerializerMethodField()
    workflow_config = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = [
            'id', 'name', 'slug', 'description', 'icon', 'category',
            'system_prompt', 'model_config', 'tool_config',
            'knowledge_config', 'guardrail_config', 'workflow_config',
            'skill_bindings', 'is_public', 'created_by_username',
            'can_edit', 'can_delete', 'created_at', 'updated_at',
        ]

    def get_skill_bindings(self, obj):
        content = self._content(obj)
        ids = [item.get('skill_id') for item in content.get('skill_bindings', [])]
        from apps.applications.models import Skill
        skills = {str(skill.id): skill for skill in Skill.objects.filter(id__in=ids)}
        return [{
            **binding,
            'slug': skills[str(binding['skill_id'])].slug,
            'name': skills[str(binding['skill_id'])].name,
        } for binding in content.get('skill_bindings', [])
          if str(binding.get('skill_id')) in skills]

    @staticmethod
    def _content(obj):
        draft = getattr(obj, 'draft', None)
        return draft.content if draft else {}

    def get_system_prompt(self, obj):
        return self._content(obj).get('system_prompt', '')

    def get_model_config(self, obj):
        return self._content(obj).get('model_config', {})

    def get_tool_config(self, obj):
        return self._content(obj).get('tool_config', [])

    def get_knowledge_config(self, obj):
        return self._content(obj).get('knowledge_config', [])

    def get_guardrail_config(self, obj):
        return self._content(obj).get('guardrail_config', {})

    def get_workflow_config(self, obj):
        return self._content(obj).get('workflow_config', {})

    def get_can_edit(self, obj):
        return _agent_permissions(obj, self.context.get('request'))[0]

    def get_can_delete(self, obj):
        return _agent_permissions(obj, self.context.get('request'))[1]


class AgentWriteSerializer(serializers.ModelSerializer):
    system_prompt = serializers.CharField()
    model_config = serializers.JSONField(required=False, default=dict)
    tool_config = serializers.JSONField(required=False, default=list)
    knowledge_config = serializers.JSONField(required=False, default=list)
    guardrail_config = serializers.JSONField(required=False, default=dict)
    workflow_config = serializers.JSONField(required=False, default=dict)
    skill_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True)

    class Meta:
        model = Agent
        fields = [
            'id', 'category', 'name', 'slug', 'description', 'icon', 'system_prompt',
            'model_config', 'tool_config', 'knowledge_config',
            'guardrail_config', 'workflow_config', 'skill_ids', 'is_public',
        ]
        read_only_fields = ['id']

    def validate_workflow_config(self, value):
        from .workflow import validate_workflow
        return validate_workflow(value)

    def validate_skill_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError('Skill 不能重复。')
        if not value:
            return value
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            raise serializers.ValidationError('无法验证 Skill 访问权限。')
        from apps.applications.models import Skill
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request, required=False)
        access = Q(visibility=Skill.Visibility.PUBLIC) | Q(owner=request.user)
        if organization is not None:
            access |= Q(organization=organization)
        allowed = set(Skill.objects.filter(
            access,
            id__in=value,
            is_active=True,
        ).values_list('id', flat=True))
        if allowed != set(value):
            raise serializers.ValidationError('包含无权使用或已停用的 Skill。')
        return value

    @transaction.atomic
    def create(self, validated_data):
        skill_ids = validated_data.pop('skill_ids', [])
        content = self._pop_definition(validated_data, skill_ids)
        content.setdefault('version', '1.0.0')
        agent = super().create(validated_data)
        self._sync_draft(agent, content)
        return agent

    @transaction.atomic
    def update(self, instance, validated_data):
        skill_ids = validated_data.pop('skill_ids', None)
        current = instance.draft.content if hasattr(instance, 'draft') else {}
        content = self._pop_definition(validated_data, skill_ids, current=current)
        agent = super().update(instance, validated_data)
        self._sync_draft(agent, content)
        return agent

    @staticmethod
    def _pop_definition(values, skill_ids, current=None):
        current = current or {}
        content = dict(current)
        for key in ('system_prompt', 'model_config', 'tool_config',
                    'knowledge_config', 'guardrail_config', 'workflow_config'):
            if key in values:
                content[key] = values.pop(key)
        if skill_ids is not None:
            content['skill_bindings'] = [
                {'skill_id': str(skill_id), 'mode': 'default', 'config': {}, 'order': order}
                for order, skill_id in enumerate(skill_ids)
            ]
        return content

    def _sync_draft(self, agent, content):
        if agent.organization_id is None:
            return
        draft = AgentDraft.objects.filter(agent=agent).first()
        actor = self.context['request'].user
        if draft is None:
            AgentDraft.objects.create(
                organization=agent.organization,
                agent=agent,
                content=content,
                updated_by=actor,
            )
            return
        draft.content = content
        draft.version += 1
        draft.updated_by = actor
        draft.save(update_fields=['content', 'version', 'updated_by', 'updated_at'])

    def to_representation(self, instance):
        return AgentDetailSerializer(instance, context=self.context).data

class AgentDeploymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDeployment
        fields = [
            'id', 'revision_id', 'previous_revision_id',
            'config_override', 'version', 'updated_by_id', 'updated_at',
        ]
        read_only_fields = fields


class AgentRevisionSerializer(serializers.ModelSerializer):
    version = serializers.SerializerMethodField()

    class Meta:
        model = AgentRevision
        fields = [
            'id', 'version', 'revision_no', 'schema_version', 'content', 'content_hash',
            'release_notes', 'created_by_id', 'created_at',
        ]
        read_only_fields = fields

    def get_version(self, obj):
        configured = (obj.content or {}).get('version')
        return str(configured or f'{obj.revision_no}.0.0')


class ExecuteAgentSerializer(serializers.Serializer):
    input_data = serializers.JSONField()

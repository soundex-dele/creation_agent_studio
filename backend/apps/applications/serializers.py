from copy import deepcopy

from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from apps.agents.models import Agent
from modules.catalog.definition import validate_application_definition
from modules.catalog.models import ApplicationDraft
from core.resource_access import (
    accessible_resources,
    can_manage_resource_permissions,
    can_update_applications,
)

from .models import Application, ApplicationCategory, ChatApplication, Skill


def application_definition(application, *, revision=None):
    if revision is not None:
        return deepcopy(revision.content)
    draft = getattr(application, 'draft', None)
    return deepcopy(draft.content) if draft is not None else {}


def enrich_chat_definition(content, user=None):
    result = deepcopy(content)
    agent_ids = [item.get('agent_id') for item in result.get('agent_bindings', [])]
    agent_query = Agent.objects.filter(id__in=agent_ids, is_active=True)
    if user is not None:
        agent_query = accessible_resources(agent_query, user)
    agents = agent_query.in_bulk()
    visible_bindings = []
    for binding in result.get('agent_bindings', []):
        agent = agents.get(binding.get('agent_id'))
        if agent:
            binding.update({
                'agent_name': agent.name,
                'agent_slug': agent.slug,
                'agent_icon': agent.icon,
            })
            visible_bindings.append(binding)
    result['agent_bindings'] = visible_bindings
    skill_ids = [item.get('skill_id') for item in result.get('skill_bindings', [])]
    skills = {str(item.id): item for item in Skill.objects.filter(id__in=skill_ids)}
    for binding in result.get('skill_bindings', []):
        skill = skills.get(str(binding.get('skill_id')))
        if skill:
            binding.update({'skill_name': skill.name, 'skill_slug': skill.slug})
    return result


class ApplicationCategorySerializer(serializers.ModelSerializer):
    app_count = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationCategory
        fields = ['id', 'name', 'slug', 'description', 'icon', 'order', 'app_count']

    def get_app_count(self, obj):
        request = self.context.get('request')
        if request is None:
            return 0
        return accessible_resources(
            obj.applications.filter(is_active=True),
            request.user,
        ).count()


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = [
            'id', 'slug', 'name', 'description', 'visibility', 'source_type',
            'source_uri', 'artifact_key', 'manifest', 'content_hash', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ApplicationRuntimeSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(source='id', read_only=True)
    organization_id = serializers.UUIDField(read_only=True, allow_null=True)
    application_slug = serializers.CharField(source='slug', read_only=True)
    application_name = serializers.CharField(source='name', read_only=True)
    application_description = serializers.CharField(source='description', read_only=True)
    application_icon = serializers.CharField(source='icon', read_only=True)
    application_color = serializers.CharField(source='color', read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'application_id', 'organization_id', 'application_slug',
            'application_name', 'application_description', 'application_icon',
            'application_color', 'kind', 'created_at', 'updated_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        definition = application_definition(
            instance, revision=self.context.get('revision'))
        if instance.kind == Application.Kind.CHAT:
            request = self.context.get('request')
            definition = enrich_chat_definition(
                definition,
                request.user if request is not None else None,
            )
        data.update(definition)
        return data


class ApplicationWriteSerializer(serializers.ModelSerializer):
    renderer_key = serializers.CharField(required=True)
    executor_key = serializers.CharField(required=True)
    input_schema = serializers.JSONField(required=False, default=dict)
    output_schema = serializers.JSONField(required=False, default=dict)
    default_config = serializers.JSONField(required=False, default=dict)
    chat_profile = serializers.JSONField(required=False)
    agent_bindings = serializers.ListField(
        child=serializers.DictField(), required=False)
    skill_bindings = serializers.ListField(
        child=serializers.DictField(), required=False)
    guided_prompts = serializers.ListField(
        child=serializers.DictField(), required=False)

    class Meta:
        model = Application
        fields = [
            'id', 'category', 'name', 'slug', 'description', 'icon', 'color',
            'tags', 'developer', 'screenshots', 'is_public', 'kind',
            'renderer_key', 'executor_key', 'input_schema', 'output_schema',
            'default_config', 'chat_profile', 'agent_bindings', 'skill_bindings',
            'guided_prompts',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        kind = attrs.get('kind', getattr(self.instance, 'kind', Application.Kind.CUSTOM))
        if self.instance is not None and kind != self.instance.kind:
            raise serializers.ValidationError(
                {'kind': '应用类型是稳定身份的一部分，不能就地变更。'})
        definition = self._definition(attrs, kind)
        try:
            validate_application_definition(definition)
        except Exception as exc:
            raise serializers.ValidationError({'definition': str(exc)}) from exc
        request = self.context['request']
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request, required=False)
        agent_ids = {item['agent_id'] for item in definition.get('agent_bindings', [])}
        if agent_ids:
            allowed = set(accessible_resources(
                Agent.objects.filter(
                    Q(organization=organization) | Q(organization__isnull=True),
                    id__in=agent_ids,
                    is_active=True,
                ),
                request.user,
            ).values_list('id', flat=True))
            if allowed != agent_ids:
                raise serializers.ValidationError(
                    {'agent_bindings': '包含无权使用的智能体。'})
        skill_ids = {item['skill_id'] for item in definition.get('skill_bindings', [])}
        if skill_ids:
            access = Q(visibility=Skill.Visibility.PUBLIC) | Q(owner=request.user)
            if organization is not None:
                access |= Q(organization=organization)
            allowed = {str(value) for value in Skill.objects.filter(
                access, is_active=True, id__in=skill_ids
            ).values_list('id', flat=True)}
            if allowed != skill_ids:
                raise serializers.ValidationError(
                    {'skill_bindings': '包含无权使用或已停用的 Skill。'})
        attrs['_definition'] = definition
        return attrs

    def _definition(self, attrs, kind):
        current = application_definition(self.instance) if self.instance else {}
        definition = {
            **current,
            'kind': kind,
            'executor_kind': ('agent' if kind == Application.Kind.CHAT
                              else attrs.get('default_config', current.get('default_config', {})).get(
                                  'executor_kind', current.get('executor_kind', 'media'))),
            'executor_key': attrs.get('executor_key', current.get('executor_key')),
            'executor_protocol_version': current.get('executor_protocol_version', 1),
            'renderer_key': attrs.get('renderer_key', current.get('renderer_key')),
            'renderer_schema_version': current.get('renderer_schema_version', 1),
            'retry_policy': attrs.get('default_config', current.get('default_config', {})).get(
                'retry_policy', current.get('retry_policy', {'max_attempts': 3, 'retry_safe': True})),
            'input_schema': attrs.get('input_schema', current.get('input_schema', {})),
            'output_schema': attrs.get('output_schema', current.get('output_schema', {})),
            'default_config': attrs.get('default_config', current.get('default_config', {})),
        }
        if kind == Application.Kind.CHAT:
            definition.update({
                'chat_profile': attrs.get('chat_profile', current.get('chat_profile', {})),
                'agent_bindings': attrs.get('agent_bindings', current.get('agent_bindings', [])),
                'skill_bindings': attrs.get('skill_bindings', current.get('skill_bindings', [])),
                'guided_prompts': attrs.get('guided_prompts', current.get('guided_prompts', [])),
            })
        return definition

    @transaction.atomic
    def create(self, validated_data):
        definition = validated_data.pop('_definition')
        self._pop_definition_fields(validated_data)
        application = super().create(validated_data)
        if application.kind == Application.Kind.CHAT:
            ChatApplication.objects.create(application=application)
        self._save_draft(application, definition)
        return application

    @transaction.atomic
    def update(self, instance, validated_data):
        definition = validated_data.pop('_definition')
        self._pop_definition_fields(validated_data)
        old_kind = instance.kind
        application = super().update(instance, validated_data)
        if application.kind == Application.Kind.CHAT:
            ChatApplication.objects.get_or_create(application=application)
        elif old_kind == Application.Kind.CHAT:
            ChatApplication.objects.filter(application=application).delete()
        self._save_draft(application, definition)
        return application

    @staticmethod
    def _pop_definition_fields(values):
        for key in (
            'renderer_key', 'executor_key', 'input_schema', 'output_schema',
            'default_config', 'chat_profile', 'agent_bindings',
            'skill_bindings', 'guided_prompts',
        ):
            values.pop(key, None)

    def _save_draft(self, application, definition):
        if application.organization_id is None:
            return
        actor = self.context['request'].user
        draft, created = ApplicationDraft.objects.get_or_create(
            application=application,
            defaults={
                'organization': application.organization,
                'content': definition,
                'updated_by': actor,
            },
        )
        if not created:
            draft.content = definition
            draft.version += 1
            draft.updated_by = actor
            draft.save(update_fields=['content', 'version', 'updated_by', 'updated_at'])

    def to_representation(self, instance):
        return ApplicationDetailSerializer(instance, context=self.context).data


class ApplicationListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    renderer_key = serializers.SerializerMethodField()
    can_manage_permissions = serializers.SerializerMethodField()

    def get_renderer_key(self, obj):
        return application_definition(obj).get('renderer_key', '')

    def get_can_manage_permissions(self, obj):
        request = self.context.get('request')
        return bool(request and can_manage_resource_permissions(obj, request.user))

    class Meta:
        model = Application
        fields = [
            'id', 'slug', 'name', 'description', 'icon', 'color', 'tags',
            'developer', 'category_name', 'category_slug', 'usage_count', 'kind',
            'renderer_key', 'visibility', 'can_manage_permissions',
        ]


class ApplicationDetailSerializer(ApplicationRuntimeSerializer):
    category = ApplicationCategorySerializer(read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_manage_permissions = serializers.SerializerMethodField()

    def get_can_edit(self, obj):
        request = self.context.get('request')
        return bool(request and can_update_applications(request.user, obj))

    def get_can_manage_permissions(self, obj):
        request = self.context.get('request')
        return bool(request and can_manage_resource_permissions(obj, request.user))

    class Meta(ApplicationRuntimeSerializer.Meta):
        fields = ApplicationRuntimeSerializer.Meta.fields + [
            'tags', 'developer', 'screenshots', 'category', 'usage_count',
            'is_public', 'visibility', 'created_by_username', 'can_edit',
            'can_manage_permissions',
        ]


class GenerateImageSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=True, max_length=2000)
    size = serializers.CharField(required=False, allow_blank=True)


class ComposeGuidedPromptSerializer(serializers.Serializer):
    prompt_id = serializers.CharField()
    answers = serializers.DictField(required=False, default=dict)

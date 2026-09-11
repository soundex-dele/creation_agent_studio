from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from .models import (
    Application, ApplicationAgentBinding, ApplicationCategory,
    ApplicationSkillBinding, ChatApplicationProfile, GuidedOption,
    GuidedPrompt, GuidedQuestion, Skill,
)
from modules.catalog.models import ApplicationDraft


class ApplicationCategorySerializer(serializers.ModelSerializer):
    app_count = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationCategory
        fields = ['id', 'name', 'slug', 'description', 'icon', 'order', 'app_count']

    def get_app_count(self, obj):
        return obj.applications.filter(is_public=True).count()


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = [
            'id', 'slug', 'name', 'description', 'visibility', 'source_type',
            'source_uri', 'artifact_key', 'manifest', 'content_hash', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class GuidedOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuidedOption
        fields = ['id', 'value', 'label', 'description', 'icon', 'order']
        read_only_fields = ['id']


class GuidedQuestionSerializer(serializers.ModelSerializer):
    options = GuidedOptionSerializer(many=True, required=False)

    class Meta:
        model = GuidedQuestion
        fields = [
            'id', 'key', 'label', 'help_text', 'type', 'placeholder', 'required',
            'default_value', 'validation', 'order', 'options',
        ]
        read_only_fields = ['id']


class GuidedPromptSerializer(serializers.ModelSerializer):
    questions = GuidedQuestionSerializer(many=True, required=False)

    class Meta:
        model = GuidedPrompt
        fields = [
            'id', 'key', 'title', 'description', 'icon', 'prompt_template',
            'action', 'is_featured', 'order', 'questions',
        ]
        read_only_fields = ['id']


class ChatApplicationProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatApplicationProfile
        exclude = ['application']


class ApplicationAgentBindingSerializer(serializers.ModelSerializer):
    agent_id = serializers.IntegerField()
    agent_name = serializers.CharField(source='agent.name', read_only=True)
    agent_slug = serializers.CharField(source='agent.slug', read_only=True)
    agent_icon = serializers.CharField(source='agent.icon', read_only=True)

    class Meta:
        model = ApplicationAgentBinding
        fields = [
            'id', 'agent_id', 'agent_name', 'agent_slug', 'agent_icon', 'label',
            'is_default', 'config_overrides', 'order',
        ]


class ApplicationSkillBindingSerializer(serializers.ModelSerializer):
    skill_id = serializers.UUIDField()
    skill_name = serializers.CharField(source='skill.name', read_only=True)
    skill_slug = serializers.CharField(source='skill.slug', read_only=True)

    class Meta:
        model = ApplicationSkillBinding
        fields = [
            'id', 'skill_id', 'skill_name', 'skill_slug', 'mode', 'config', 'order',
        ]


class ApplicationRuntimeSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(source='id', read_only=True)
    organization_id = serializers.UUIDField(read_only=True, allow_null=True)
    application_slug = serializers.CharField(source='slug', read_only=True)
    application_name = serializers.CharField(source='name', read_only=True)
    application_description = serializers.CharField(source='description', read_only=True)
    application_icon = serializers.CharField(source='icon', read_only=True)
    application_color = serializers.CharField(source='color', read_only=True)
    chat_profile = ChatApplicationProfileSerializer(read_only=True)
    agent_bindings = ApplicationAgentBindingSerializer(many=True, read_only=True)
    skill_bindings = ApplicationSkillBindingSerializer(many=True, read_only=True)
    guided_prompts = GuidedPromptSerializer(many=True, read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'application_id', 'organization_id', 'application_slug', 'application_name',
            'application_description', 'application_icon', 'application_color',
            'kind', 'renderer_key', 'executor_key', 'input_schema', 'output_schema',
            'default_config', 'chat_profile', 'agent_bindings', 'skill_bindings',
            'guided_prompts', 'created_at', 'updated_at',
        ]


class ApplicationWriteSerializer(serializers.ModelSerializer):
    chat_profile = ChatApplicationProfileSerializer(required=False)
    agent_bindings = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True)
    skill_bindings = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True)
    guided_prompts = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'category', 'name', 'slug', 'description', 'icon', 'color',
            'tags', 'developer', 'screenshots', 'is_public', 'kind', 'renderer_key',
            'executor_key', 'input_schema', 'output_schema', 'default_config',
            'chat_profile', 'agent_bindings', 'skill_bindings', 'guided_prompts',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        kind = attrs.get('kind', getattr(self.instance, 'kind', None))
        renderer_key = attrs.get(
            'renderer_key', getattr(self.instance, 'renderer_key', ''))
        agent_values = attrs.get('agent_bindings')
        if kind == Application.Kind.CHAT:
            if renderer_key != 'chat':
                raise serializers.ValidationError(
                    {'renderer_key': '聊天应用必须使用 chat renderer。'})
            if self.instance is None and not agent_values:
                raise serializers.ValidationError(
                    {'agent_bindings': '聊天应用至少需要一个智能体。'})

        request = self.context['request']
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(request, required=False)

        if agent_values is not None:
            try:
                agent_ids = {int(item.get('agent_id')) for item in agent_values
                             if item.get('agent_id') is not None}
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {'agent_bindings': '智能体 ID 格式错误。'})
            if len(agent_ids) != len(agent_values):
                raise serializers.ValidationError(
                    {'agent_bindings': '智能体不能为空或重复。'})
            if agent_ids:
                from apps.agents.models import Agent
                access = Q(is_public=True) | Q(created_by=request.user)
                if organization is not None:
                    access |= Q(organization=organization)
                allowed = set(Agent.objects.filter(
                    access, id__in=agent_ids).values_list('id', flat=True))
                if agent_ids != allowed:
                    raise serializers.ValidationError(
                        {'agent_bindings': '包含无权使用的智能体。'})
            defaults = sum(bool(item.get('is_default')) for item in agent_values)
            if kind == Application.Kind.CHAT and defaults != 1:
                raise serializers.ValidationError(
                    {'agent_bindings': '聊天应用必须且只能指定一个默认智能体。'})

        skill_values = attrs.get('skill_bindings')
        if skill_values is not None:
            skill_ids = {str(item.get('skill_id')) for item in skill_values
                         if item.get('skill_id') is not None}
            if len(skill_ids) != len(skill_values):
                raise serializers.ValidationError(
                    {'skill_bindings': 'Skill 不能为空或重复。'})
            if skill_ids:
                access = Q(visibility=Skill.Visibility.PUBLIC) | Q(owner=request.user)
                if organization is not None:
                    access |= Q(organization=organization)
                allowed = {str(value) for value in Skill.objects.filter(
                    access, is_active=True, id__in=skill_ids
                ).values_list('id', flat=True)}
                if skill_ids != allowed:
                    raise serializers.ValidationError(
                        {'skill_bindings': '包含无权使用或已停用的 Skill。'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        nested = self._pop_nested(validated_data)
        application = super().create(validated_data)
        self._replace_nested(application, **nested)
        from .services import validate_application
        validate_application(application)
        self._sync_runtime_draft(application)
        return application

    @transaction.atomic
    def update(self, instance, validated_data):
        nested = self._pop_nested(validated_data)
        application = super().update(instance, validated_data)
        self._replace_nested(application, replace_only_present=True, **nested)
        from .services import validate_application
        validate_application(application)
        self._sync_runtime_draft(application)
        return application

    def _sync_runtime_draft(self, application):
        """Persist the editable runtime definition for the canonical app."""
        if application.organization_id is None:
            return
        default_config = application.default_config or {}
        content = {
            'executor_kind': default_config.get('executor_kind') or (
                'agent' if application.kind == Application.Kind.CHAT else 'media'
            ),
            'executor_key': application.executor_key,
            'executor_protocol_version': 1,
            'renderer_key': application.renderer_key or None,
            'renderer_schema_version': 1,
            'retry_policy': default_config.get('retry_policy') or {
                'max_attempts': 3,
                'retry_safe': True,
            },
            'input_schema': application.input_schema or {},
            'output_schema': application.output_schema or {},
            'default_config': default_config,
        }
        actor = self.context['request'].user
        draft = ApplicationDraft.objects.filter(application=application).first()
        if draft is None:
            ApplicationDraft.objects.create(
                organization=application.organization,
                application=application,
                content=content,
                updated_by=actor,
            )
            return
        draft.content = content
        draft.version += 1
        draft.updated_by = actor
        draft.save(update_fields=['content', 'version', 'updated_by', 'updated_at'])

    @staticmethod
    def _pop_nested(validated_data):
        return {
            'profile': validated_data.pop('chat_profile', None),
            'agents': validated_data.pop('agent_bindings', None),
            'skills': validated_data.pop('skill_bindings', None),
            'prompts': validated_data.pop('guided_prompts', None),
        }

    @staticmethod
    def _replace_nested(application, profile=None, agents=None, skills=None,
                        prompts=None, replace_only_present=False):
        if profile is not None:
            ChatApplicationProfile.objects.update_or_create(
                application=application, defaults=profile)
        elif not replace_only_present:
            ChatApplicationProfile.objects.filter(application=application).delete()
        if agents is not None:
            application.agent_bindings.all().delete()
            ApplicationAgentBinding.objects.bulk_create([
                ApplicationAgentBinding(application=application, **item)
                for item in agents
            ])
        if skills is not None:
            application.skill_bindings.all().delete()
            ApplicationSkillBinding.objects.bulk_create([
                ApplicationSkillBinding(application=application, **item)
                for item in skills
            ])
        if prompts is not None:
            application.guided_prompts.all().delete()
            for source in prompts:
                item = dict(source)
                questions = item.pop('questions', [])
                prompt = GuidedPrompt.objects.create(application=application, **item)
                for question_source in questions:
                    question_value = dict(question_source)
                    options = question_value.pop('options', [])
                    question = GuidedQuestion.objects.create(
                        guided_prompt=prompt, **question_value)
                    GuidedOption.objects.bulk_create([
                        GuidedOption(question=question, **option) for option in options])


class ApplicationListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'slug', 'name', 'description', 'icon', 'color', 'tags',
            'developer', 'category_name', 'category_slug', 'usage_count', 'kind',
            'renderer_key',
        ]


class ApplicationDetailSerializer(ApplicationRuntimeSerializer):
    category = ApplicationCategorySerializer(read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True)
    can_edit = serializers.SerializerMethodField()

    def get_can_edit(self, obj):
        request = self.context.get('request')
        return bool(
            request and request.user.is_authenticated
            and (request.user.is_superuser or obj.created_by_id == request.user.id)
        )

    class Meta(ApplicationRuntimeSerializer.Meta):
        fields = ApplicationRuntimeSerializer.Meta.fields + [
            'tags', 'developer', 'screenshots', 'category', 'usage_count',
            'is_public', 'created_by_username', 'can_edit',
        ]


class GenerateImageSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=True, max_length=2000)
    size = serializers.CharField(required=False, allow_blank=True)


class ComposeGuidedPromptSerializer(serializers.Serializer):
    prompt_id = serializers.UUIDField()
    answers = serializers.DictField(required=False, default=dict)

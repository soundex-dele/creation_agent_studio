from rest_framework import serializers

from .models import (
    Application,
    ApplicationAgentBinding,
    ApplicationCategory,
    ApplicationSkillBinding,
    ChatApplicationProfile,
    GuidedOption,
    GuidedPrompt,
    GuidedQuestion,
    Skill,
)


class ApplicationCategorySerializer(serializers.ModelSerializer):
    app_count = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationCategory
        fields = ["id", "name", "slug", "description", "icon", "order", "app_count"]

    def get_app_count(self, obj):
        return obj.applications.filter(is_public=True).count()


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = [
            "id", "slug", "name", "description", "visibility", "source_type",
            "source_uri", "artifact_key", "manifest", "content_hash", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class GuidedOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuidedOption
        fields = ["id", "value", "label", "description", "icon", "order"]
        read_only_fields = ["id"]


class GuidedQuestionSerializer(serializers.ModelSerializer):
    options = GuidedOptionSerializer(many=True, required=False)

    class Meta:
        model = GuidedQuestion
        fields = [
            "id", "key", "label", "help_text", "type", "placeholder", "required",
            "default_value", "validation", "order", "options",
        ]
        read_only_fields = ["id"]


class GuidedPromptSerializer(serializers.ModelSerializer):
    questions = GuidedQuestionSerializer(many=True, required=False)

    class Meta:
        model = GuidedPrompt
        fields = [
            "id", "key", "title", "description", "icon", "prompt_template",
            "action", "is_featured", "order", "questions",
        ]
        read_only_fields = ["id"]


class ChatApplicationProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatApplicationProfile
        exclude = ["application"]


class ApplicationAgentBindingSerializer(serializers.ModelSerializer):
    agent_id = serializers.IntegerField()
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    agent_slug = serializers.CharField(source="agent.slug", read_only=True)
    agent_icon = serializers.CharField(source="agent.icon", read_only=True)

    class Meta:
        model = ApplicationAgentBinding
        fields = [
            "id", "agent_id", "agent_name", "agent_slug", "agent_icon", "label",
            "is_default", "config_overrides", "order",
        ]


class ApplicationSkillBindingSerializer(serializers.ModelSerializer):
    skill_id = serializers.UUIDField()
    skill_name = serializers.CharField(source="skill.name", read_only=True)
    skill_slug = serializers.CharField(source="skill.slug", read_only=True)

    class Meta:
        model = ApplicationSkillBinding
        fields = [
            "id", "skill_id", "skill_name", "skill_slug", "mode", "config", "order",
        ]


class ApplicationRuntimeSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(source="id", read_only=True)
    organization_id = serializers.UUIDField(read_only=True, allow_null=True)
    application_slug = serializers.CharField(source="slug", read_only=True)
    application_name = serializers.CharField(source="name", read_only=True)
    application_description = serializers.CharField(source="description", read_only=True)
    application_icon = serializers.CharField(source="icon", read_only=True)
    application_color = serializers.CharField(source="color", read_only=True)
    chat_profile = ChatApplicationProfileSerializer(read_only=True)
    agent_bindings = ApplicationAgentBindingSerializer(many=True, read_only=True)
    skill_bindings = ApplicationSkillBindingSerializer(many=True, read_only=True)
    guided_prompts = GuidedPromptSerializer(many=True, read_only=True)

    class Meta:
        model = Application
        fields = [
            "id", "application_id", "organization_id", "application_slug", "application_name",
            "application_description", "application_icon", "application_color",
            "kind", "renderer_key", "executor_key", "input_schema", "output_schema",
            "default_config", "chat_profile", "agent_bindings", "skill_bindings",
            "guided_prompts", "created_at", "updated_at",
        ]


class ApplicationListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)

    class Meta:
        model = Application
        fields = [
            "id", "slug", "name", "description", "icon", "color", "tags",
            "developer", "category_name", "category_slug", "usage_count", "kind",
            "renderer_key",
        ]


class ApplicationDetailSerializer(ApplicationRuntimeSerializer):
    category = ApplicationCategorySerializer(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    can_edit = serializers.SerializerMethodField()

    def get_can_edit(self, obj):
        request = self.context.get("request")
        return bool(
            request
            and request.user.is_authenticated
            and (request.user.is_superuser or obj.created_by_id == request.user.id)
        )

    class Meta(ApplicationRuntimeSerializer.Meta):
        fields = ApplicationRuntimeSerializer.Meta.fields + [
            "tags", "developer", "screenshots", "category", "usage_count",
            "is_public", "created_by_username", "can_edit",
        ]


class ComposeGuidedPromptSerializer(serializers.Serializer):
    prompt_id = serializers.UUIDField()
    answers = serializers.DictField(required=False, default=dict)

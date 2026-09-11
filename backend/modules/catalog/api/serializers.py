from rest_framework import serializers

from modules.catalog.models import (
    Application,
    ApplicationDeployment,
    ApplicationDraft,
    ApplicationRevision,
)


def validate_json_object(value, field_name):
    if not isinstance(value, dict):
        raise serializers.ValidationError(f"{field_name} must be a JSON object")
    return value


class ApplicationSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    owner_id = serializers.ReadOnlyField(source="created_by_id")

    class Meta:
        model = Application
        fields = (
            "id",
            "organization_id",
            "owner_id",
            "name",
            "slug",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )


class CreateApplicationSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(max_length=160)
    slug = serializers.SlugField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    content = serializers.JSONField(default=dict)

    def validate_content(self, value):
        return validate_json_object(value, "content")


class ApplicationDraftSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    organization_id = serializers.UUIDField(read_only=True)
    updated_by_id = serializers.ReadOnlyField()

    class Meta:
        model = ApplicationDraft
        fields = (
            "id",
            "organization_id",
            "application_id",
            "content",
            "version",
            "updated_by_id",
            "created_at",
            "updated_at",
        )


class UpdateApplicationDraftSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    content = serializers.JSONField()

    def validate_content(self, value):
        return validate_json_object(value, "content")


class PublishApplicationSerializer(serializers.Serializer):
    expected_draft_version = serializers.IntegerField(min_value=1)
    release_notes = serializers.CharField(required=False, allow_blank=True, default="")


class ApplicationRevisionSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    organization_id = serializers.UUIDField(read_only=True)
    created_by_id = serializers.ReadOnlyField()

    class Meta:
        model = ApplicationRevision
        fields = (
            "id",
            "organization_id",
            "application_id",
            "revision_no",
            "schema_version",
            "content",
            "content_hash",
            "release_notes",
            "created_by_id",
            "created_at",
        )


class ApplicationDeploymentSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    organization_id = serializers.UUIDField(read_only=True)
    revision_id = serializers.UUIDField(read_only=True)
    previous_revision_id = serializers.UUIDField(read_only=True, allow_null=True)
    updated_by_id = serializers.ReadOnlyField()

    class Meta:
        model = ApplicationDeployment
        fields = (
            "id",
            "organization_id",
            "application_id",
            "environment",
            "revision_id",
            "previous_revision_id",
            "config_override",
            "version",
            "updated_by_id",
            "updated_at",
        )


class SwitchApplicationDeploymentSerializer(serializers.Serializer):
    revision_id = serializers.UUIDField()
    expected_version = serializers.IntegerField(min_value=0)
    config_override = serializers.JSONField(required=False, default=dict)

    def validate_config_override(self, value):
        return validate_json_object(value, "config_override")


class RollbackApplicationDeploymentSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)

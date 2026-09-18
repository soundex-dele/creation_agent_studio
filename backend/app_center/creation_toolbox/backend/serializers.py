from pathlib import Path

from rest_framework import serializers

from .models import (
    Copywriting,
    CreationProject,
    CreationWorkspace,
    MaterialFolder,
    MediaAsset,
    Recording,
    Scene,
    Script,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    project_count = serializers.IntegerField(read_only=True, default=0)
    asset_count = serializers.IntegerField(read_only=True, default=0)
    recording_count = serializers.IntegerField(read_only=True, default=0)
    copywriting_count = serializers.IntegerField(read_only=True, default=0)
    script_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CreationWorkspace
        fields = [
            "id", "application_id", "name", "storage_mode", "audio_sample_rate",
            "transcription_language", "project_count", "asset_count",
            "recording_count", "copywriting_count", "script_count", "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "application_id", "storage_mode", "created_at", "updated_at"]

    def validate_audio_sample_rate(self, value):
        if value not in {16000, 22050, 44100, 48000}:
            raise serializers.ValidationError("请选择受支持的采样率。")
        return value


class ProjectSerializer(serializers.ModelSerializer):
    asset_count = serializers.IntegerField(read_only=True, default=0)
    recording_count = serializers.IntegerField(read_only=True, default=0)
    script_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CreationProject
        fields = [
            "id", "name", "description", "asset_count", "recording_count",
            "script_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("工程名称不能为空。")
        return value


class FolderSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, default=0)
    project_id = serializers.UUIDField(read_only=True)
    parent_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = MaterialFolder
        fields = ["id", "project_id", "parent_id", "name", "item_count", "created_at"]
        read_only_fields = ["id", "project_id", "created_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise serializers.ValidationError("请输入有效的文件夹名称。")
        return value


class AssetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    project_id = serializers.UUIDField(read_only=True)
    folder_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = MediaAsset
        fields = [
            "id", "project_id", "folder_id", "name", "kind", "mime_type", "size",
            "file_url", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "project_id", "kind", "mime_type", "size", "file_url", "created_at",
            "updated_at",
        ]

    def get_file_url(self, instance):
        return instance.file.url if instance.file else ""

    def validate_name(self, value):
        value = Path(value).name.strip()
        if not value:
            raise serializers.ValidationError("文件名不能为空。")
        return value


class RecordingSerializer(serializers.ModelSerializer):
    audio_url = serializers.SerializerMethodField()
    project_id = serializers.UUIDField(read_only=True, allow_null=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default="")

    class Meta:
        model = Recording
        fields = [
            "id", "project_id", "project_name", "name", "audio_url", "mime_type",
            "duration_ms", "transcription", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "project_name", "audio_url", "mime_type", "transcription", "created_at",
            "updated_at",
        ]

    def get_audio_url(self, instance):
        return instance.audio.url if instance.audio else ""


class CopywritingSerializer(serializers.ModelSerializer):
    style_label = serializers.CharField(source="get_style_display", read_only=True)
    project_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Copywriting
        fields = [
            "id", "project_id", "title", "content", "style", "style_label",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "style_label", "created_at", "updated_at"]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("标题不能为空。")
        return value

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("文案内容不能为空。")
        return value


class GenerateCopywritingSerializer(serializers.Serializer):
    topic = serializers.CharField(max_length=200)
    style = serializers.ChoiceField(choices=Copywriting.Style.choices)
    project_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_topic(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("请输入创作主题。")
        return value


class SceneSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    image_asset_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Scene
        fields = [
            "id", "title", "description", "image_asset_id", "image_url",
            "duration_seconds", "order", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "image_url", "created_at", "updated_at"]

    def get_image_url(self, instance):
        return instance.image_asset.file.url if instance.image_asset_id else ""

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("场景标题不能为空。")
        return value

    def validate_duration_seconds(self, value):
        if value < 1 or value > 3600:
            raise serializers.ValidationError("场景时长应在 1 到 3600 秒之间。")
        return value


class ScriptSerializer(serializers.ModelSerializer):
    scenes = SceneSerializer(many=True, read_only=True)
    total_duration_seconds = serializers.SerializerMethodField()
    project_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Script
        fields = [
            "id", "project_id", "title", "description", "scenes",
            "total_duration_seconds", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "scenes", "total_duration_seconds", "created_at", "updated_at"]

    def get_total_duration_seconds(self, instance):
        return sum(scene.duration_seconds for scene in instance.scenes.all())

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("脚本标题不能为空。")
        return value

from pathlib import Path

from rest_framework import serializers

from .models import (
    Copywriting,
    CreationProject,
    CreationWorkspace,
    MaterialFolder,
    MediaAsset,
    MetricSnapshot,
    Platform,
    ProjectStageEvent,
    Publication,
    Recording,
    Scene,
    Script,
    TopicIdea,
    VideoDeliverable,
)


def _clean_string_list(value, label):
    if not isinstance(value, list):
        raise serializers.ValidationError(f"{label}必须是数组。")
    cleaned = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _validate_platforms(value):
    cleaned = _clean_string_list(value, "目标平台")
    allowed = set(Platform.values)
    invalid = [item for item in cleaned if item not in allowed]
    if invalid:
        raise serializers.ValidationError(f"不支持的平台：{', '.join(invalid)}")
    return cleaned


class WorkspaceSerializer(serializers.ModelSerializer):
    project_count = serializers.IntegerField(read_only=True, default=0)
    asset_count = serializers.IntegerField(read_only=True, default=0)
    recording_count = serializers.IntegerField(read_only=True, default=0)
    copywriting_count = serializers.IntegerField(read_only=True, default=0)
    script_count = serializers.IntegerField(read_only=True, default=0)
    topic_count = serializers.IntegerField(read_only=True, default=0)
    publication_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CreationWorkspace
        fields = [
            "id", "application_id", "name", "storage_mode", "audio_sample_rate",
            "transcription_language", "project_count", "asset_count",
            "recording_count", "copywriting_count", "script_count", "created_at",
            "topic_count", "publication_count", "updated_at",
        ]
        read_only_fields = ["id", "application_id", "storage_mode", "created_at", "updated_at"]

    def validate_audio_sample_rate(self, value):
        if value not in {16000, 22050, 44100, 48000}:
            raise serializers.ValidationError("请选择受支持的采样率。")
        return value


class TopicSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    project_count = serializers.IntegerField(read_only=True, default=0)
    publication_count = serializers.IntegerField(read_only=True, default=0)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = TopicIdea
        fields = [
            "id", "title", "notes", "source_name", "source_url", "target_platforms",
            "tags", "status", "status_label", "project_count", "publication_count",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status_label", "project_count", "publication_count", "created_by",
            "created_by_name", "created_at", "updated_at",
        ]

    def validate_title(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("选题标题不能为空。")
        return value

    def validate_tags(self, value):
        return _clean_string_list(value, "标签")[:20]

    def validate_target_platforms(self, value):
        return _validate_platforms(value)


class TopicBulkUpdateSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=200
    )
    status = serializers.ChoiceField(choices=TopicIdea.Status.choices, required=False)
    add_tags = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, default=list
    )
    remove_tags = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, default=list
    )

    def validate(self, attrs):
        if not any(key in attrs for key in ("status", "add_tags", "remove_tags")):
            raise serializers.ValidationError("请选择要批量修改的内容。")
        return attrs


class TopicCreateProjectSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    target_platforms = serializers.ListField(
        child=serializers.ChoiceField(choices=Platform.choices), required=False
    )

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("工程名称不能为空。")
        return value


class ProjectSerializer(serializers.ModelSerializer):
    asset_count = serializers.IntegerField(read_only=True, default=0)
    recording_count = serializers.IntegerField(read_only=True, default=0)
    script_count = serializers.IntegerField(read_only=True, default=0)
    deliverable_count = serializers.IntegerField(read_only=True, default=0)
    publication_count = serializers.IntegerField(read_only=True, default=0)
    topic_title = serializers.CharField(source="topic.title", read_only=True, default="")
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True, default="")
    reviewer_name = serializers.CharField(source="reviewer.username", read_only=True, default="")

    class Meta:
        model = CreationProject
        fields = [
            "id", "topic", "topic_title", "name", "description", "stage", "stage_label",
            "owner", "owner_name", "reviewer", "reviewer_name", "planned_publish_at",
            "target_platforms", "tags", "archived_at", "asset_count", "recording_count",
            "script_count", "deliverable_count", "publication_count", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "topic_title", "stage", "stage_label", "archived_at", "owner_name",
            "reviewer_name", "created_at", "updated_at",
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("工程名称不能为空。")
        return value

    def validate_tags(self, value):
        return _clean_string_list(value, "标签")[:20]

    def validate_target_platforms(self, value):
        return _validate_platforms(value)


class ProjectStageEventSerializer(serializers.ModelSerializer):
    from_stage_label = serializers.CharField(source="get_from_stage_display", read_only=True)
    to_stage_label = serializers.CharField(source="get_to_stage_display", read_only=True)
    changed_by_name = serializers.CharField(source="changed_by.username", read_only=True)

    class Meta:
        model = ProjectStageEvent
        fields = [
            "id", "from_stage", "from_stage_label", "to_stage", "to_stage_label",
            "note", "changed_by", "changed_by_name", "created_at",
        ]
        read_only_fields = fields


class ProjectStageTransitionSerializer(serializers.Serializer):
    to_stage = serializers.ChoiceField(choices=CreationProject.Stage.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


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


class VideoDeliverableSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    platform_label = serializers.CharField(source="get_platform_display", read_only=True)
    review_status_label = serializers.CharField(
        source="get_review_status_display", read_only=True
    )
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.username", read_only=True, default=""
    )

    class Meta:
        model = VideoDeliverable
        fields = [
            "id", "project", "name", "version_label", "platform", "platform_label",
            "file", "file_url", "external_url", "duration_ms", "review_status",
            "review_status_label", "review_note", "created_by", "created_by_name",
            "reviewed_by", "reviewed_by_name", "reviewed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "project", "file_url", "platform_label", "review_status_label",
            "created_by", "created_by_name", "reviewed_by", "reviewed_by_name",
            "reviewed_at", "created_at", "updated_at",
        ]
        extra_kwargs = {"file": {"write_only": True, "required": False}}

    def get_file_url(self, instance):
        return instance.file.url if instance.file else ""

    def validate(self, attrs):
        file_value = attrs.get("file", getattr(self.instance, "file", None))
        url_value = attrs.get("external_url", getattr(self.instance, "external_url", ""))
        if not file_value and not url_value:
            raise serializers.ValidationError("请上传成片或填写外部链接。")
        return attrs


class MetricSnapshotSerializer(serializers.ModelSerializer):
    play_rate = serializers.SerializerMethodField()
    completion_rate = serializers.SerializerMethodField()
    engagement_rate = serializers.SerializerMethodField()
    follow_rate = serializers.SerializerMethodField()
    conversion_rate = serializers.SerializerMethodField()

    class Meta:
        model = MetricSnapshot
        fields = [
            "id", "publication", "observed_on", "impressions", "views", "completions",
            "likes", "comments", "shares", "saves", "followers_gained", "conversions",
            "average_watch_seconds", "extra_metrics", "play_rate", "completion_rate",
            "engagement_rate", "follow_rate", "conversion_rate", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "publication", "play_rate", "completion_rate", "engagement_rate",
            "follow_rate", "conversion_rate", "created_at", "updated_at",
        ]

    @staticmethod
    def _rate(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None

    def get_play_rate(self, obj):
        return self._rate(obj.views, obj.impressions)

    def get_completion_rate(self, obj):
        return self._rate(obj.completions, obj.views)

    def get_engagement_rate(self, obj):
        return self._rate(obj.likes + obj.comments + obj.shares + obj.saves, obj.views)

    def get_follow_rate(self, obj):
        return self._rate(obj.followers_gained, obj.views)

    def get_conversion_rate(self, obj):
        return self._rate(obj.conversions, obj.views)


class PublicationSerializer(serializers.ModelSerializer):
    platform_label = serializers.CharField(source="get_platform_display", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    latest_metrics = serializers.SerializerMethodField()

    class Meta:
        model = Publication
        fields = [
            "id", "project", "project_name", "deliverable", "platform", "platform_label",
            "platform_name", "account_name", "title", "external_post_id", "post_url",
            "published_at", "latest_metrics", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "project_name", "platform_label", "latest_metrics", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        external_id = attrs.get(
            "external_post_id", getattr(self.instance, "external_post_id", "")
        )
        post_url = attrs.get("post_url", getattr(self.instance, "post_url", ""))
        if not external_id and not post_url:
            raise serializers.ValidationError("作品 ID 和作品链接至少填写一项。")
        platform = attrs.get("platform", getattr(self.instance, "platform", ""))
        platform_name = attrs.get(
            "platform_name", getattr(self.instance, "platform_name", "")
        )
        if platform == Platform.OTHER and not platform_name.strip():
            raise serializers.ValidationError({"platform_name": "请填写平台名称。"})
        return attrs

    def get_latest_metrics(self, instance):
        snapshot = instance.metric_snapshots.order_by("-observed_on", "-created_at").first()
        return MetricSnapshotSerializer(snapshot).data if snapshot else None

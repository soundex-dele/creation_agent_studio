import hashlib
import json
from rest_framework import serializers
from .models import Recording, ActionItem


class UploadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=["meeting", "interview"])
    recorded_on = serializers.DateField()
    language = serializers.ChoiceField(choices=["zh", "en", "auto"], default="zh")
    audio = serializers.FileField()


class MetadataSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    kind = serializers.ChoiceField(choices=["meeting", "interview"], required=False)
    recorded_on = serializers.DateField(required=False)


class SegmentEditSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=50)
    text = serializers.CharField(max_length=6000, allow_blank=True, trim_whitespace=False)


class TranscriptSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    segments = SegmentEditSerializer(many=True, allow_empty=False)


def action_revision(action):
    snapshot = [action.title, action.description, action.priority, str(action.due_date), action.segment_ids]
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")).hexdigest()


class ActionSerializer(serializers.ModelSerializer):
    revision = serializers.SerializerMethodField()
    description = serializers.CharField(max_length=18000, allow_blank=True, required=False)
    priority = serializers.ChoiceField(choices=[1, 2, 3], required=False)

    class Meta:
        model = ActionItem
        fields = ["id", "analysis_version", "revision", "title", "description", "priority", "due_date", "segment_ids", "todo_id", "confirmed_at"]
        read_only_fields = ["id", "analysis_version", "revision", "segment_ids", "todo_id", "confirmed_at"]

    def get_revision(self, obj):
        return action_revision(obj)


class RecordingSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    stale = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    run_id = serializers.UUIDField(source="active_run_id", read_only=True, allow_null=True)

    class Meta:
        model = Recording
        fields = ["id", "title", "kind", "recorded_on", "language", "filename", "size", "duration", "segments",
                  "version", "analysis_version", "analysis", "status", "stale", "error", "actions", "run_id", "created_at", "updated_at"]

    def get_status(self, obj):
        run = obj.active_run
        if not run and obj.stage in ("queued", "transcribing", "analyzing"):
            return "failed"
        if run and run.status in ("failed", "cancelled", "cancelling", "queued"):
            return run.status
        if run and run.status == "running" and obj.stage in ("queued", "completed"):
            return "analyzing" if obj.stage == "completed" else "running"
        return obj.stage

    def get_error(self, obj):
        if obj.active_run and obj.active_run.status == "failed":
            return obj.error or "处理失败，请重试；如持续失败，请检查执行服务和模型配置。"
        return obj.error

    def get_stale(self, obj):
        return bool(obj.analysis_version and obj.analysis_version != obj.version)

    def get_actions(self, obj):
        return ActionSerializer(obj.actions.filter(analysis_version=obj.analysis_version), many=True).data


class RecordingSummarySerializer(RecordingSerializer):
    class Meta(RecordingSerializer.Meta):
        fields = [field for field in RecordingSerializer.Meta.fields if field not in ("segments", "analysis", "actions")]

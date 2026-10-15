from rest_framework import serializers
from .models import CleanerEntry, CleanerTask


class ScanInput(serializers.Serializer):
    request_key = serializers.CharField(max_length=160)
    mode = serializers.ChoiceField(choices=["analysis", "large", "cache"])
    root = serializers.CharField(max_length=32760)
    minimum_bytes = serializers.IntegerField(min_value=1, max_value=1024 ** 5, default=100 * 1024 ** 2)


class PreviewInput(serializers.Serializer):
    scan_id = serializers.UUIDField()
    entry_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=1000)


class CleanupInput(serializers.Serializer):
    request_key = serializers.CharField(max_length=160)
    token = serializers.CharField(max_length=1024)


class EntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CleanerEntry
        fields = ["id", "path", "parent", "kind", "size", "modified_at", "cleanable"]


class TaskSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()

    def get_summary(self, task):
        if task.kind != "cleanup":
            return {}
        from django.db.models import Count
        return {row["state"]: row["count"] for row in task.results.values("state").annotate(count=Count("id"))}

    class Meta:
        model = CleanerTask
        fields = ["id", "kind", "state", "parameters", "processed", "total_bytes", "skipped", "deleted_bytes",
                  "free_before", "free_after", "message", "created_at", "finished_at", "cancel_requested", "summary"]

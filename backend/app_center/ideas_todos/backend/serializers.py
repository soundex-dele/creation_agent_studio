from django.utils import timezone
from rest_framework import serializers

from .models import Idea, Todo


class IdeaSerializer(serializers.ModelSerializer):
    body = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=40), max_length=20, required=False,
    )

    def validate_tags(self, value):
        return list(dict.fromkeys(value))

    class Meta:
        model = Idea
        fields = ["id", "title", "body", "tags", "is_pinned", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class TodoSerializer(serializers.ModelSerializer):
    description = serializers.CharField(required=False, allow_blank=True, max_length=20000)

    def create(self, validated_data):
        if validated_data.get("is_completed"):
            validated_data["completed_at"] = timezone.now()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        completed = validated_data.get("is_completed", instance.is_completed)
        if completed != instance.is_completed:
            validated_data["completed_at"] = timezone.now() if completed else None
        return super().update(instance, validated_data)

    class Meta:
        model = Todo
        fields = [
            "id", "title", "description", "priority", "due_date", "is_completed",
            "completed_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "completed_at", "created_at", "updated_at"]


class ListFilters(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    tag = serializers.CharField(required=False, allow_blank=True, max_length=40)
    status = serializers.ChoiceField(
        choices=["all", "pending", "completed", "today", "overdue"], default="pending",
    )
    priority = serializers.ChoiceField(choices=Todo.Priority.choices, required=False)
    today = serializers.DateField(required=False)

    def validate(self, data):
        if data["status"] in ("today", "overdue") and "today" not in data:
            raise serializers.ValidationError({"today": "请提供本地日期。"})
        return data

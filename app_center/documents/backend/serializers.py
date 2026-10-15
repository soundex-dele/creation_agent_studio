from rest_framework import serializers
from .content import validate_content
from .models import Document


class DocumentSerializer(serializers.ModelSerializer):
    permission = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.username", read_only=True)

    class Meta:
        model = Document
        fields = ["id", "title", "content", "plain_text", "version", "owner", "owner_name", "permission", "created_at", "updated_at"]
        read_only_fields = ["id", "plain_text", "version", "owner", "created_at", "updated_at"]

    def get_permission(self, obj):
        user = self.context["request"].user
        if obj.owner_id == user.id:
            return "owner"
        return next((g.role for g in obj.grants.all() if g.user_id == user.id), "viewer")

    def validate_content(self, value):
        return validate_content(value)


class DocumentUpdateSerializer(DocumentSerializer):
    version = serializers.IntegerField(min_value=1, required=True)


class GrantSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    role = serializers.ChoiceField(choices=["viewer", "editor"])


class AssistantSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=10000)
    version = serializers.IntegerField(min_value=1)
    selection = serializers.CharField(max_length=20000, required=False, allow_blank=True, default="", trim_whitespace=False)
    selection_from = serializers.IntegerField(min_value=0, max_value=1000000, default=0)
    selection_to = serializers.IntegerField(min_value=0, max_value=1000000, default=0)

    def validate(self, attrs):
        if attrs["selection_to"] < attrs["selection_from"]:
            raise serializers.ValidationError("选区位置无效。")
        return attrs

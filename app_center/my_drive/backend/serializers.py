from rest_framework import serializers
from .models import DriveEntry, DriveUpload


def validate_name(value):
    value = value.strip()
    if not value or value in {".", ".."} or any(ord(c) < 32 or c in '/\\' for c in value):
        raise serializers.ValidationError("名称不能为空，也不能包含路径分隔符或控制字符。")
    return value


class EntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = DriveEntry
        fields = ["id", "parent", "name", "kind", "size", "media_type", "trash_root", "created_at", "updated_at"]


class UploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriveUpload
        fields = ["id", "parent", "entry", "name", "size", "last_modified", "offset", "chunk_size", "state", "updated_at"]


class FolderInput(serializers.Serializer):
    name = serializers.CharField(max_length=240, validators=[validate_name])
    parent = serializers.UUIDField(required=False, allow_null=True)


class UploadInput(FolderInput):
    size = serializers.IntegerField(min_value=0)
    last_modified = serializers.IntegerField(min_value=0, default=0)


class ActionInput(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    action = serializers.ChoiceField(choices=["rename", "move", "trash", "restore", "purge"])
    name = serializers.CharField(max_length=240, required=False, validators=[validate_name])
    parent = serializers.UUIDField(required=False, allow_null=True)

from rest_framework import serializers


class GenerateSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=8000, trim_whitespace=True)
    orientation = serializers.ChoiceField(choices=["auto", "square", "landscape", "portrait"], default="auto")
    reference_id = serializers.UUIDField(required=False)
    source_artifact_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if attrs.get("reference_id") and attrs.get("source_artifact_id"):
            raise serializers.ValidationError("每次只能使用一张参考图。")
        return {key: str(value) for key, value in attrs.items()}

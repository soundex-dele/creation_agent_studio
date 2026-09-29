from rest_framework import serializers


class AnimationInputSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["generate", "export"], default="generate")
    prompt = serializers.CharField(max_length=16000, required=False)
    aspect = serializers.ChoiceField(choices=["16:9", "9:16", "1:1"], default="16:9")
    duration = serializers.IntegerField(min_value=5, max_value=120, default=30)
    style = serializers.CharField(max_length=1000, allow_blank=True, default="简洁清晰，注重信息层次")
    asset_ids = serializers.ListField(child=serializers.UUIDField(), max_length=10, default=list)
    source_run_id = serializers.UUIDField(required=False)

    def validate(self, data):
        if data["action"] == "export":
            if not data.get("source_run_id"):
                raise serializers.ValidationError("导出必须指定动画版本。")
            return {"action": "export", "source_run_id": str(data["source_run_id"])}
        if not data.get("prompt"):
            raise serializers.ValidationError({"prompt": "请填写动画内容或修改要求。"})
        data["asset_ids"] = [str(value) for value in data["asset_ids"]]
        if len(set(data["asset_ids"])) != len(data["asset_ids"]):
            raise serializers.ValidationError("素材不能重复。")
        if data.get("source_run_id"):
            data["source_run_id"] = str(data["source_run_id"])
        return data

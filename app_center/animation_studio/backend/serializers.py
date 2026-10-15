from rest_framework import serializers


class AnimationInputSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["generate", "export", "storyboard", "scene", "speech", "transcribe", "batch"], default="generate")
    prompt = serializers.CharField(max_length=16000, required=False)
    aspect = serializers.ChoiceField(choices=["16:9", "9:16", "1:1"], default="16:9")
    duration = serializers.IntegerField(min_value=5, max_value=120, default=30)
    style = serializers.CharField(max_length=1000, allow_blank=True, default="简洁清晰，注重信息层次")
    asset_ids = serializers.ListField(child=serializers.UUIDField(), max_length=10, default=list)
    source_run_id = serializers.UUIDField(required=False)
    project_id = serializers.UUIDField(required=False)
    draft_revision = serializers.IntegerField(min_value=1, required=False)
    document = serializers.JSONField(required=False)
    scene_id = serializers.CharField(max_length=64, required=False)
    instruction = serializers.CharField(max_length=16000, required=False)
    voice = serializers.CharField(max_length=200, required=False)
    speed = serializers.FloatField(min_value=0.5, max_value=2, required=False)
    asset_id = serializers.UUIDField(required=False)
    batch_id = serializers.UUIDField(required=False)
    export_options = serializers.JSONField(required=False)

    def validate(self, data):
        from .studio_validation import validate_task
        if "document" in data or data["action"] == "batch":
            if data["action"] != "batch" and (not data.get("project_id") or not data.get("draft_revision")):
                raise serializers.ValidationError("分镜任务缺少作品或草稿修订号。")
            for key in ("project_id", "asset_id", "batch_id"):
                if key in data: data[key] = str(data[key])
            return validate_task(data)
        if data["action"] == "export":
            if not data.get("source_run_id"):
                raise serializers.ValidationError("导出必须指定动画版本。")
            result = {"action": "export", "source_run_id": str(data["source_run_id"])}
            if "export_options" in data: result["export_options"] = data["export_options"]
            return validate_task(result)
        if data["action"] != "generate":
            raise serializers.ValidationError("该任务需要分镜工程。")
        if not data.get("prompt"):
            raise serializers.ValidationError({"prompt": "请填写动画内容或修改要求。"})
        data["asset_ids"] = [str(value) for value in data["asset_ids"]]
        if len(set(data["asset_ids"])) != len(data["asset_ids"]):
            raise serializers.ValidationError("素材不能重复。")
        if data.get("source_run_id"):
            data["source_run_id"] = str(data["source_run_id"])
        return data

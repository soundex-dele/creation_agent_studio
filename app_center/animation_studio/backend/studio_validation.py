from rest_framework.exceptions import ValidationError
from .documents import number, validate_document


def export_options(data):
    if not isinstance(data, dict): raise ValidationError("导出设置无效。")
    result = {"format": data.get("format", "mp4"), "resolution": data.get("resolution", 1080), "quality": data.get("quality", "standard"), "cover_frame": data.get("cover_frame", 0)}
    if result["format"] not in ("mp4", "gif", "png", "srt", "vtt") or result["resolution"] not in (720, 1080) or result["quality"] not in ("standard", "high"):
        raise ValidationError("导出格式、清晰度或质量无效。")
    number(result["cover_frame"], 0, 3599, "封面帧", True)
    if "scene_id" in data:
        if not isinstance(data["scene_id"], str): raise ValidationError("分镜 ID 无效。")
        result["scene_id"] = data["scene_id"]
    return result


def validate_task(values):
    action = values.get("action")
    if action == "batch": return values
    if action == "export":
        if "export_options" in values: values["export_options"] = export_options(values["export_options"])
        return values
    doc = validate_document(values.get("document"), complete=action not in ("storyboard", "generate"))
    if action in ("scene", "speech"):
        item = next((s for s in doc["scenes"] if s["id"] == values.get("scene_id")), None)
        if not item: raise ValidationError("请选择分镜。")
        if item.get("locked"): raise ValidationError("请先解锁目标分镜。")
        if action == "scene" and not str(values.get("instruction", "")).strip(): raise ValidationError("请输入修改要求。")
    if action == "speech":
        number(values.get("speed", 1), 0.5, 2, "语速")
        if not isinstance(values.get("voice"), str) or not values["voice"]: raise ValidationError("请选择音色。")
    if action == "storyboard" and any(s.get("locked") for s in doc["scenes"]): raise ValidationError("重新编排前请解锁场景。")
    if action == "transcribe" and not values.get("asset_id"): raise ValidationError("请选择录音。")
    values["document"] = doc
    return values

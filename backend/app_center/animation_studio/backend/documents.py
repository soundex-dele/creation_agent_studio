"""Versioned scene documents shared by HTTP validation and workers."""
import copy
import json
import math
import re
import uuid

from rest_framework.exceptions import ValidationError

FONTS = ["Noto Sans SC", "sans-serif", "serif", "monospace"]


def scene(title="新场景", body="", frames=300):
    return {"id": str(uuid.uuid4()), "title": title, "body": body, "narration": body,
            "description": "", "frames": frames, "assets": [], "locked": False,
            "style": {"color": "#4f46e5", "background": "#ffffff", "font": "Noto Sans SC"}, "source": ""}


def empty_document():
    return {"schema_version": 2, "prompt": "", "aspect": "16:9", "style": "简洁清晰", "scenes": [],
            "audio": [], "subtitles": [], "subtitle_style": {"enabled": True, "font": "Noto Sans SC", "size": 40, "color": "#ffffff", "position": "bottom"}, "brand": {}}


def number(value, low, high, label, integer=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValidationError(f"{label}须在 {low}–{high} 之间。")
    return value


def validate_document(value, *, previous=None, complete=False):
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False)) > 2000000:
        raise ValidationError("分镜工程格式无效或过大。")
    doc = {**empty_document(), **copy.deepcopy(value)}
    if doc["schema_version"] != 2 or doc["aspect"] not in ("16:9", "9:16", "1:1"):
        raise ValidationError("不支持的工程版本或画幅。")
    if not isinstance(doc["prompt"], str) or len(doc["prompt"]) > 16000 or not isinstance(doc["style"], str) or len(doc["style"]) > 1000:
        raise ValidationError("创作要求或风格过长。")
    scenes = doc["scenes"]
    if not isinstance(scenes, list) or len(scenes) > 30 or (complete and not scenes):
        raise ValidationError("请提供 1–30 个分镜。")
    ids = set()
    for item in scenes:
        if not isinstance(item, dict):
            raise ValidationError("分镜格式无效。")
        identifier = item.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identifier) or identifier in ids:
            raise ValidationError("分镜 ID 无效或重复。")
        ids.add(identifier)
        number(item.get("frames"), 1, 3600, "分镜帧数", True)
        for key in ("title", "body", "narration", "description", "source"):
            if not isinstance(item.get(key, ""), str) or len(item.get(key, "")) > (150000 if key == "source" else 16000):
                raise ValidationError("分镜文字无效或过长。")
        if not isinstance(item.get("locked", False), bool) or not isinstance(item.get("assets", []), list):
            raise ValidationError("锁定状态或素材格式无效。")
        for asset in item.get("assets", []):
            try:
                uuid.UUID(str(asset))
            except (ValueError, TypeError):
                raise ValidationError("素材 ID 无效。")
        validate_style(item.get("style", {}))
    total = sum(item["frames"] for item in scenes)
    if total > 3600 or (complete and total < 150):
        raise ValidationError("动画总时长须为 5–120 秒。")
    if previous:
        existing = {item["id"]: item for item in previous.get("scenes", []) if item.get("locked")}
        incoming = {item["id"]: item for item in scenes}
        for identifier, old in existing.items():
            new = incoming.get(identifier)
            # Unlock is an explicit separate edit; combining it with changes is rejected.
            if not new or {**old, "locked": new.get("locked", False)} != new:
                raise ValidationError("请先解锁场景，再修改或删除。")
        if existing and doc["aspect"] != previous.get("aspect"):
            raise ValidationError("更改画幅前请解锁所有场景。")
    validate_style(doc["subtitle_style"])
    if doc["subtitle_style"].get("position", "bottom") not in ("top", "center", "bottom"):
        raise ValidationError("字幕位置无效。")
    number(doc["subtitle_style"].get("size", 40), 12, 120, "字幕字号")
    if not isinstance(doc["audio"], list) or len(doc["audio"]) > 50:
        raise ValidationError("音轨最多 50 条。")
    for track in doc["audio"]:
        if not isinstance(track, dict) or track.get("role") not in ("narration", "music", "effect"):
            raise ValidationError("音轨格式无效。")
        if track.get("scene_id") and track["scene_id"] not in ids:
            raise ValidationError("音轨引用的分镜不存在。")
        for key, default, maximum in (("start", 0, 3600), ("trim_start", 0, 3600), ("frames", total or 3600, 3600), ("fade_in", 0, 3600), ("fade_out", 0, 3600)):
            number(track.get(key, default), 0, maximum, "音轨帧数", True)
        number(track.get("volume", 1), 0, 2, "音量")
        if not track.get("asset_id") or not isinstance(track.get("loop", False), bool):
            raise ValidationError("音轨必须引用素材，循环状态须为布尔值。")
        if track.get("frames", 1) <= 0: raise ValidationError("音轨播放长度必须大于零。")
    if not isinstance(doc["subtitles"], list) or len(doc["subtitles"]) > 2000:
        raise ValidationError("字幕格式无效。")
    for sub in doc["subtitles"]:
        if not isinstance(sub, dict) or not isinstance(sub.get("text"), str) or len(sub["text"]) > 2000:
            raise ValidationError("字幕内容无效。")
        number(sub.get("start"), 0, 3600, "字幕开始帧", True)
        number(sub.get("end"), sub["start"] + 1, total or 3600, "字幕结束帧", True)
    if not isinstance(doc["brand"], dict):
        raise ValidationError("品牌格式无效。")
    validate_style(doc["brand"])
    if len(asset_ids(doc)) > 50: raise ValidationError("每个版本最多使用50个素材。")
    for identifier in asset_ids(doc):
        try: uuid.UUID(identifier)
        except (ValueError, TypeError): raise ValidationError("素材 ID 无效。")
    return doc


def validate_style(style):
    if not isinstance(style, dict):
        raise ValidationError("样式格式无效。")
    for key in ("color", "background"):
        if key in style and (not isinstance(style[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", style[key])):
            raise ValidationError("颜色须为六位十六进制色值。")
    if style.get("font", "Noto Sans SC") not in FONTS:
        raise ValidationError("请选择受支持的字体。")


def asset_ids(doc):
    values = {str(a) for s in doc.get("scenes", []) for a in s.get("assets", [])}
    values.update(str(a["asset_id"]) for a in doc.get("audio", []) if a.get("asset_id"))
    if doc.get("brand", {}).get("logo"):
        values.add(str(doc["brand"]["logo"]))
    return sorted(values)


def builtins():
    result = []
    for key, title, headings in [("knowledge", "知识科普", ["问题", "核心知识", "总结"]), ("product", "产品介绍", ["产品亮点", "使用场景", "立即了解"]), ("process", "流程演示", ["第一步", "第二步", "第三步"]), ("data", "数据解读", ["数据概览", "关键变化", "结论"])]:
        doc = empty_document()
        doc["scenes"] = [scene(text, "请填写内容", 300) for text in headings]
        for index, item in enumerate(doc["scenes"]):
            item["id"] = f"scene-{index + 1}"
        result.append({"id": key, "name": title, "kind": "template", "builtin": True, "data": {"document": doc,
            "fields": [{"name": f"text{index + 1}", "scene_id": item["id"], "property": "body", "type": "text"} for index, item in enumerate(doc["scenes"])]}})
    return result

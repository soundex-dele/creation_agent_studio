"""Schema-only validation shared by manifests, personal presets and snapshots."""
import math
import re


def save_policy(question):
    if question.get("type") == "file" or question["key"] in {
        "html_path", "output_directory", "drafts_root", "assets", "file_path",
    }:
        return "never"
    return question.get("preset_save") or ("optional" if question["key"] in {
        "source", "article", "content", "topic", "text", "material",
    } else "preference")


def validate_preset_values(prompt, values):
    if not isinstance(values, dict):
        raise ValueError("模板参数必须为对象。")
    questions = {q["key"]: q for q in prompt.get("questions", [])}
    for key, value in values.items():
        q = questions.get(key)
        if q is None:
            raise ValueError(f"模板字段 {key} 已不存在，请调整模板。")
        if save_policy(q) == "never":
            raise ValueError(f"{q['label']} 不允许保存到模板。")
        if save_policy(q) == 'optional' and isinstance(value, str) and '\n' not in value.strip() and re.match(
            r'^(?:[A-Za-z]:[\\/]|/|\./|\.\./|~/|file:)|^\S+\.(?:md|html?|docx?|pdf|txt|png|jpe?g|mp[34]|wav)$', value.strip(), re.I
        ):
            raise ValueError(f"{q['label']} 中的文件路径不能保存到模板。")
        kind = q["type"]
        valid = isinstance(value, str)
        if kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value))
        elif kind == "multi_choice":
            valid = isinstance(value, list) and all(isinstance(v, str) for v in value)
        if not valid:
            raise ValueError(f"模板字段 {key} 的类型不正确。")
        if kind in ("single_choice", "multi_choice"):
            allowed = {o["value"] for o in q.get("options", [])}
            if any(v not in allowed for v in (value if isinstance(value, list) else [value])):
                raise ValueError(f"模板字段 {key} 包含失效选项，请调整模板。")
    return values

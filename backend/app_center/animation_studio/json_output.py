"""Decode model-authored JSON without altering generated text or source code."""
import json


def decode_json_object(text):
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        # Models sometimes emit literal newlines/tabs inside quoted strings.
        # strict=False permits these characters only inside strings; invalid
        # quoting, escapes, truncation and trailing content still fail parsing.
        result = json.loads(value, strict=False)
    except json.JSONDecodeError as exc:
        raise ValueError("AI 返回的内容格式不正确，请重新生成。") from exc
    if not isinstance(result, dict):
        raise ValueError("AI 返回的内容格式不正确，请重新生成。")
    return result

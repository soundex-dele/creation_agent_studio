import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ...json_output import decode_json_object
from ...runtime import decode_result
from ... import studio_runtime
from ..documents import empty_document


@pytest.mark.parametrize("character", ["\n", "\r", "\t"])
def test_literal_control_characters_keep_model_text(character):
    prefix = '{"body":"'
    content = "x" * (432 - len(prefix)) + character + "第二段"
    value = prefix + content + '"}'
    with pytest.raises(json.JSONDecodeError, match="Invalid control character") as caught:
        json.loads(value)
    assert caught.value.pos == 432
    assert decode_json_object(value)["body"] == content


@pytest.mark.parametrize("fenced", [False, True])
def test_valid_escaped_source_is_not_rewritten(fenced):
    source = 'const label = "一行\\n两行";\nexport default () => <div>{label}</div>;'
    data = {"source": source, "title": "测试", "storyboard": "第一幕\n第二幕"}
    value = json.dumps(data, ensure_ascii=False)
    if fenced:
        value = "```json\n" + value + "\n```"
    assert decode_json_object(value) == data
    assert decode_result(value) == data


@pytest.mark.parametrize("value", [
    '{"body":"没有结束',
    '{"body":"未转义的"引号"}',
    '{"body":"bad\\qescape"}',
    '{"body":"正文"} trailing text',
    '{\x00"body":"正文"}',
    '[]', 'null', '"plain text"',
])
def test_structurally_invalid_results_still_fail_with_actionable_message(value):
    with pytest.raises(ValueError, match="AI 返回的内容格式不正确，请重新生成"):
        decode_json_object(value)


def test_legacy_source_accepts_literal_newlines_but_keeps_source_validation():
    source = "export default function Animation() {\n\treturn <div>动画</div>;\n}"
    assert decode_result('{"source":"' + source + '"}')["source"] == source
    with pytest.raises(ValueError, match="有效动画源码"):
        decode_result('{"source":42}')
    with pytest.raises(ValueError, match="源码过长"):
        decode_result(json.dumps({"source": "x" * 150001}))


def test_storyboard_uses_tolerant_parser_without_changing_scene_text(monkeypatch, tmp_path):
    response = SimpleNamespace(success=True, model="test", usage=Mock(), content='{"scenes":[{"title":"第一幕","body":"第一行\n第二行","narration":"旁白\t说明","frames":300}]}')
    adapter = Mock(); adapter.return_value.complete.return_value = response
    monkeypatch.setattr(studio_runtime, "CodexAdapter", adapter)
    monkeypatch.setattr(studio_runtime, "enforce_member_token_quota", Mock())
    record_usage = Mock(); monkeypatch.setattr(studio_runtime, "record_usage", record_usage)
    run = SimpleNamespace(organization=object(), owner=object())
    app = SimpleNamespace(id="app")
    sink = Mock(cancelled=False)
    document = empty_document(); document["prompt"] = "测试分镜"
    result = studio_runtime.storyboard(run, app, {}, sink, document, tmp_path)
    assert result["scenes"][0]["body"] == "第一行\n第二行"
    assert result["scenes"][0]["narration"] == "旁白\t说明"
    adapter.return_value.complete.assert_called_once()
    record_usage.assert_called_once()

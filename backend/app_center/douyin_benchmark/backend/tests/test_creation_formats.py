import pytest
from types import SimpleNamespace
from ..analysis import validate_script
from ..creation_formats import format_instruction
from ..serializers import TaskInput
from .test_douyin import script


def test_old_clients_default_to_talking_head_and_invalid_formats_are_rejected():
    serializer = TaskInput(data={"kind": "topics"})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["production_format"] == "talking_head"
    assert "真人口播" in format_instruction({})
    serializer = TaskInput(data={"kind": "topics", "production_format": "unknown"})
    assert not serializer.is_valid()
    assert "production_format" in serializer.errors


def test_animation_duration_limit_does_not_limit_other_formats():
    animation = TaskInput(data={"kind": "topics", "production_format": "animation", "duration": 121})
    assert not animation.is_valid()
    assert "duration" in animation.errors
    screencast = TaskInput(data={"kind": "topics", "production_format": "screencast", "duration": 600})
    assert screencast.is_valid(), screencast.errors


@pytest.mark.parametrize("kind,expected", [("talking_head", "景别"), ("screencast", "鼠标或键盘操作"), ("animation", "运动过程"), ("live_action", "运镜"), ("mixed", "具体形式")])
def test_prompt_requires_executable_format_specific_storyboards(kind, expected):
    prompt = format_instruction({"production_format": kind})
    assert expected in prompt
    assert "不照搬参考作品的制作形式" in prompt


def test_legacy_scripts_and_silent_shots_remain_editable():
    assert validate_script(script()) == script()
    silent = {**script(), "production_format": "animation", "scenes": [{"time": "0–5秒", "visual": "标题淡入", "spoken": ""}]}
    assert validate_script(silent) == silent
    with pytest.raises(ValueError, match="视频形式"):
        validate_script({**script(), "production_format": []})
    with pytest.raises(ValueError, match="30个分镜"):
        validate_script({**silent, "scenes": silent["scenes"] * 31})


def test_legacy_topic_history_defaults_without_mutating_its_frozen_input(monkeypatch):
    from .. import services
    brief = {"theme": "阅读", "duration": 60}
    source = SimpleNamespace(input={"brief": brief, "reference": {}}, output={"topics": [{"title": "问题"}]})
    monkeypatch.setattr(services, "get_object_or_404", lambda *args, **kwargs: source)
    result, _ = services.frozen_input(SimpleNamespace(tasks=object()), {
        "kind": "script", "source_task_id": "old-topics", "topic_index": 0, "production_format": "animation",
    })
    assert result["brief"]["production_format"] == "talking_head"
    assert "production_format" not in brief

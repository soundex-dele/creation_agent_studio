from unittest.mock import Mock

import pytest

from .. import analysis


def claim(refs):
    return {"claims": [{"type": "observation", "text": "以提问开场", "refs": refs}]}


def test_explicit_ids_and_one_repair_preserve_evidence(monkeypatch):
    model = Mock(side_effect=[claim(["metadata", "s1-s2"]), claim(["s1", "s2", "s1"])])
    monkeypatch.setattr(analysis, "call_model", model)
    data = {"segments": [{"id": "s1", "text": "为什么？"}, {"id": "s2", "text": "举个例子"}], "metadata": {"id": "platform-id"}}
    result = analysis.call_claims(None, "分析口播", data, {}, {"s1", "s2"})
    assert result == claim(["s1", "s2"])
    first, second = model.call_args_list
    assert '本次 refs 唯一允许的来源 ID：["s1", "s2"]' in first.args[1]
    assert "上一次结果校验失败" in second.args[1]
    assert first.args[2] is data and second.args[2] is data


def test_valid_result_does_not_retry(monkeypatch):
    model = Mock(return_value=claim(["s1"]))
    monkeypatch.setattr(analysis, "call_model", model)
    assert analysis.call_claims(None, "分析", {}, {}, {"s1"}) == claim(["s1"])
    model.assert_called_once()


@pytest.mark.parametrize("refs", [["missing"], ["s1-s2"], [], [1], ["s1", "missing"]])
def test_invalid_references_are_never_silently_accepted(monkeypatch, refs):
    model = Mock(return_value=claim(refs))
    monkeypatch.setattr(analysis, "call_model", model)
    with pytest.raises(ValueError, match="修正后仍未通过校验"):
        analysis.call_claims(None, "分析", {}, {}, {"s1", "s2"})
    assert model.call_count == 2


def test_provider_and_quota_errors_are_not_retried(monkeypatch):
    model = Mock(side_effect=ValueError("模型请求失败"))
    monkeypatch.setattr(analysis, "call_model", model)
    with pytest.raises(ValueError, match="模型请求失败"):
        analysis.call_claims(None, "分析", {}, {}, {"s1"})
    model.assert_called_once()


def test_cancellation_prevents_repair(monkeypatch):
    model = Mock(return_value=claim(["missing"]))
    monkeypatch.setattr(analysis, "call_model", model)
    with pytest.raises(InterruptedError):
        analysis.call_claims(None, "分析", {}, {}, {"s1"}, cancelled=Mock(side_effect=[False, False, True]))
    model.assert_called_once()


def test_visual_repair_keeps_frames(monkeypatch):
    model = Mock(side_effect=[claim(["s1"]), claim(["f0"])])
    monkeypatch.setattr(analysis, "call_model", model)
    frames = [{"id": "f0", "time": 0, "key": "private-frame.jpg"}]
    assert analysis.call_claims(None, "观察", {}, {}, {"f0"}, frames=frames) == claim(["f0"])
    assert all(call.kwargs["frames"] is frames for call in model.call_args_list)

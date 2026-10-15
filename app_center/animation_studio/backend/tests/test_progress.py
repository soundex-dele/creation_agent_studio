from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest

from ... import runtime, studio_runtime
from ..documents import empty_document, scene


def test_ai_progress_reports_throttled_counts_without_source_or_reasoning(monkeypatch):
    sink = Mock(cancelled=False)
    monkeypatch.setattr(runtime.time, "monotonic", Mock(side_effect=[0, 1, 2]))
    report = runtime.ai_progress(sink, {"stage": "generating", "scene_index": 2, "scene_total": 3})
    report("agent.item", {"type": "reasoning", "text": "private"})
    report("output.delta", {"text": "source"})
    report("output.delta", {"text": " code"})
    report("output.snapshot", {"text": "replacement"})
    assert sink.emit.call_count == 2
    payloads = [call.args[1] for call in sink.emit.call_args_list]
    assert payloads[0] == {"stage": "generating", "scene_index": 2, "scene_total": 3,
                           "activity": "responding", "characters": 6}
    assert payloads[1]["characters"] == 11
    assert all("text" not in payload for payload in payloads)


def test_scene_progress_tracks_repair_and_preview_stages(settings, tmp_path, monkeypatch):
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    doc = empty_document(); doc["prompt"] = "测试"; doc["scenes"] = [scene("第一幕", "内容", 150)]
    run = SimpleNamespace(owner=None, organization_id="org", id="run")
    sink = Mock(cancelled=False)
    monkeypatch.setattr(studio_runtime, "project_for", Mock(return_value=object()))
    monkeypatch.setattr(studio_runtime, "document_assets", Mock())
    monkeypatch.setattr(studio_runtime, "require_engine", Mock(return_value="node"))
    broken = "export default ()=>Object.prototype"
    repaired = "export default ({scene})=>Object.hasOwn(scene, 'title') ? scene.title : null"
    ask = Mock(side_effect=[{"source": broken}, {"source": repaired}])
    monkeypatch.setattr(studio_runtime, "ask", ask)
    monkeypatch.setattr(studio_runtime, "prepare", Mock())
    monkeypatch.setattr(studio_runtime, "persist_result", Mock(return_value={}))
    # First validation fails; the repaired scene and final combined preview succeed.
    monkeypatch.setattr(studio_runtime, "run_process", Mock(side_effect=[RuntimeError("build failed"), None, None]))
    studio_runtime.execute_studio({}, sink, run, None, {"action": "scene", "project_id": "project", "document": doc,
                                                       "scene_id": doc["scenes"][0]["id"], "instruction": "调整画面"})
    progress = [call.args[1] for call in sink.emit.call_args_list if call.args[0] == "progress.updated"]
    assert [item["stage"] for item in progress] == ["generating", "building_preview", "build_failed", "repairing", "building_preview", "building_preview"]
    assert progress[2]["attempt"] == 1
    assert progress[2]["error_message"] == "build failed"
    assert progress[2]["will_retry"] is True
    assert progress[3]["attempt"] == 2
    assert progress[2]["scene_index"] == progress[2]["scene_total"] == 1
    assert progress[2]["scene_title"] == "第一幕"
    assert ask.call_args_list[0].args[5]["previous_source"] == ""
    repair_request = ask.call_args_list[1].args[5]
    assert repair_request["previous_source"] == broken
    assert repair_request["build_error"] == "build failed"
    assert "Object.hasOwn(data, key)" in ask.call_args_list[1].args[4]


def test_structured_build_error_preserves_cause_and_retry_decision(tmp_path):
    message = f"预览浏览器执行失败：{tmp_path}/preview.html"
    log = "browser log\nANIMATION_BUILD_ERROR " + json.dumps({"code": "preview_browser_error", "retryable": False, "message": message})
    error = runtime.build_error(log, tmp_path)
    assert str(error) == "预览浏览器执行失败：<project>/preview.html"
    assert error.code == "preview_browser_error"
    assert error.retryable is False
    assert runtime.build_error("old compiler error", tmp_path).retryable is True
    assert "old compiler error" in str(runtime.build_error("old compiler error", tmp_path))


@pytest.mark.parametrize("retryable", [True, False])
def test_scene_only_repairs_source_errors_and_preserves_diagnostics(settings, tmp_path, monkeypatch, retryable):
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    doc = empty_document(); doc["scenes"] = [scene("第一幕", "内容", 150)]
    run = SimpleNamespace(owner=None, organization_id="org", id="run")
    sink = Mock(cancelled=False)
    monkeypatch.setattr(studio_runtime, "project_for", Mock(return_value=object()))
    monkeypatch.setattr(studio_runtime, "document_assets", Mock())
    monkeypatch.setattr(studio_runtime, "require_engine", Mock(return_value="node"))
    ask = Mock(return_value={"source": "export default ()=>null"})
    monkeypatch.setattr(studio_runtime, "ask", ask)
    monkeypatch.setattr(studio_runtime, "prepare", Mock())
    persist = Mock()
    monkeypatch.setattr(studio_runtime, "persist_result", persist)
    monkeypatch.setattr(studio_runtime, "run_process", Mock(side_effect=runtime.AnimationBuildError(
        "具体失败原因", code="preview_runtime_error" if retryable else "preview_timeout", retryable=retryable)))
    with pytest.raises(RuntimeError, match="具体失败原因") as result:
        studio_runtime.execute_studio({}, sink, run, None, {"action":"scene", "project_id":"project", "document":doc,
                                                          "scene_id":doc["scenes"][0]["id"], "instruction":"修改"})
    assert ask.call_count == (3 if retryable else 1)
    assert ("修复两次" in str(result.value)) is retryable
    failures = [call.args[1] for call in sink.emit.call_args_list if call.args[1].get("stage") == "build_failed"]
    assert [item["attempt"] for item in failures] == ([1, 2, 3] if retryable else [1])
    assert [item["will_retry"] for item in failures] == ([True, True, False] if retryable else [False])
    assert all(item["error_message"] == "具体失败原因" and item["scene_title"] == "第一幕" for item in failures)
    persist.assert_not_called()
    artifacts = [call.kwargs for call in sink.create_artifact.call_args_list]
    assert artifacts[-1]["content"] == "具体失败原因"
    if retryable:
        assert artifacts[0]["kind"] == "animation-diagnostic-source"
        assert artifacts[0]["content"] == "export default ()=>null"
        assert ask.call_args_list[1].args[5]["build_error"] == "具体失败原因"

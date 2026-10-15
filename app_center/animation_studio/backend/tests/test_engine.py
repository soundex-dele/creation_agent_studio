from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ... import runtime, studio_runtime
from ..documents import empty_document


def test_engine_reports_missing_node(monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="PATH"):
        runtime.require_engine()


def test_engine_reports_incomplete_dependency_install(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "/test/node")
    monkeypatch.setattr(runtime, "ENGINE", tmp_path)
    package = tmp_path / "node_modules" / "remotion"
    package.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="npm ci --prefix"):
        runtime.require_engine()
    (package / "package.json").write_text('{}', encoding="utf-8")
    assert runtime.require_engine() == "/test/node"


@pytest.mark.parametrize("action", ["generate", "scene"])
def test_missing_engine_fails_before_ai_work(action, monkeypatch):
    monkeypatch.setattr(studio_runtime, "project_for", Mock())
    monkeypatch.setattr(studio_runtime, "document_assets", Mock())
    monkeypatch.setattr(studio_runtime, "require_engine", Mock(side_effect=RuntimeError("missing engine")))
    storyboard = Mock()
    monkeypatch.setattr(studio_runtime, "storyboard", storyboard)
    ask = Mock()
    monkeypatch.setattr(studio_runtime, "ask", ask)
    with pytest.raises(RuntimeError, match="missing engine"):
        studio_runtime.execute_studio({}, Mock(), SimpleNamespace(owner=None), None,
                                      {"action": action, "project_id": "test", "document": empty_document()})
    storyboard.assert_not_called()
    ask.assert_not_called()

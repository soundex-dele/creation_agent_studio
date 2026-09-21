import json

import pytest

from apps.workflows.artifacts import artifact_instructions, collect_workflow_artifacts, workflow_artifact_baseline


def snapshot(contract):
    return {"workflow_step_key": "writer", "effective_config": {"workflow_artifacts": contract}}


def test_file_outputs_are_resolved_from_declared_files_not_agent_prose(tmp_path):
    (tmp_path / "article.md").write_text("# 实际正文", encoding="utf-8")
    definition = snapshot({"article_md": "article.md"})
    assert "article.md" in artifact_instructions(definition)
    assert collect_workflow_artifacts(definition, str(tmp_path)) == {"article_md": str(tmp_path / "article.md")}
    assert collect_workflow_artifacts({}, None) == {}


def test_missing_empty_or_outside_files_cannot_complete_a_node(tmp_path):
    with pytest.raises(ValueError, match="未生成或为空"):
        collect_workflow_artifacts(snapshot({"article": "missing.md"}), str(tmp_path))
    (tmp_path / "empty.md").touch()
    with pytest.raises(ValueError, match="未生成或为空"):
        collect_workflow_artifacts(snapshot({"article": "empty.md"}), str(tmp_path))
    with pytest.raises(ValueError, match="工作目录内"):
        collect_workflow_artifacts(snapshot({"article": "../outside.md"}), str(tmp_path))


def test_pagination_report_must_pass_before_export(tmp_path):
    report = tmp_path / "report.json"
    definition = snapshot({"report": {"path": "report.json", "status": "complete"}})
    report.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="校验未通过"):
        collect_workflow_artifacts(definition, str(tmp_path))
    report.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    assert collect_workflow_artifacts(definition, str(tmp_path))["report"] == str(report)


def test_retry_cannot_reuse_a_stale_file_as_new_output(tmp_path):
    (tmp_path / "old.md").write_text("previous run", encoding="utf-8")
    definition = snapshot({"article": "old.md"})
    baseline = workflow_artifact_baseline(definition, str(tmp_path))
    with pytest.raises(ValueError, match="本次执行中更新"):
        collect_workflow_artifacts(definition, str(tmp_path), baseline)

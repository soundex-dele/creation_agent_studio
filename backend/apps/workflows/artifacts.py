"""Explicit file outputs for workflow Agent steps; never infer paths from prose."""
import json
import mimetypes
from pathlib import Path


def artifact_contract(snapshot):
    if not snapshot.get("workflow_step_key"):
        return {}
    contract = (snapshot.get("effective_config") or {}).get("workflow_artifacts") or {}
    if not isinstance(contract, dict):
        raise ValueError("workflow_artifacts 必须是输出字段与文件路径的映射。")
    return contract


def workspace_file(workspace, value):
    if not workspace or not isinstance(value, str) or not value.strip():
        raise ValueError("工作流文件必须提供有效的工作目录与路径。")
    root = Path(workspace).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("工作流产物必须位于本次工作目录内。")
    return path


def artifact_instructions(snapshot):
    contract = artifact_contract(snapshot)
    if not contract:
        return ""
    return (
        "\n\n工作流文件交接要求：以下路径相对于当前工作目录。"
        "实际生成并校验这些文件后才能完成任务；目录不存在时创建目录。"
        "只写入声明的产物及配套资源，不修改其他并行分支的文件。"
        "重跑时重新生成本节点产物，不能仅引用旧文件。"
        "不要把说明、候选标题或发布建议混入正文文件。"
        "声明 status 的 JSON 报告必须具有对应的 status 字段。\n"
        + json.dumps(contract, ensure_ascii=False, indent=2)
    )


def workflow_artifact_baseline(snapshot, workspace):
    baseline = {}
    for field, descriptor in artifact_contract(snapshot).items():
        spec = {"path": descriptor} if isinstance(descriptor, str) else descriptor
        if not isinstance(spec, dict):
            raise ValueError(f"工作流产物 {field} 的定义无效。")
        path = workspace_file(workspace, spec.get("path"))
        baseline[field] = path.stat().st_mtime_ns if path.is_file() else None
    return baseline


def collect_workflow_artifacts(snapshot, workspace, baseline=None):
    artifacts = {}
    for field, descriptor in artifact_contract(snapshot).items():
        spec = {"path": descriptor} if isinstance(descriptor, str) else descriptor
        if not isinstance(spec, dict):
            raise ValueError(f"工作流产物 {field} 的定义无效。")
        path = workspace_file(workspace, spec.get("path"))
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"工作流产物未生成或为空：{path.name}")
        if baseline is not None and baseline.get(field) == path.stat().st_mtime_ns:
            raise ValueError(f"工作流产物未在本次执行中更新：{path.name}")
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if "status" in spec and (
                not isinstance(data, dict) or data.get("status") != spec["status"]
            ):
                raise ValueError(f"工作流产物校验未通过：{path.name}")
        artifacts[field] = str(path)
    return artifacts


def publish_workflow_artifacts(artifacts, sink):
    """Publish only files already validated by the workflow output contract."""
    seen = set()
    for field, value in artifacts.items():
        path = Path(value)
        if path in seen:
            continue
        seen.add(path)
        sink.create_artifact(
            kind="result", filename=path.name, content=path.read_bytes(),
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            metadata={"output_field": field},
        )

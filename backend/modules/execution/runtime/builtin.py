"""Built-in adapters for the unified durable execution plane."""
import os
import importlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v",
}


def _is_within_allowed_roots(path, allowed_roots):
    return any(path == root or root in path.parents for root in allowed_roots)

def execute_batch_transcribe(run_payload, sink):
    """Execute batch transcription through the durable Run API."""
    config = {
        **dict(run_payload.get("effective_config") or {}),
        **dict(run_payload.get("input") or {}),
    }
    folder_path = Path(config.get("folder", "")).expanduser().resolve(strict=False)
    allowed_roots = [
        Path(root).expanduser().resolve(strict=False)
        for root in run_payload.get("allowed_roots", [])
    ]
    if not allowed_roots or not _is_within_allowed_roots(folder_path, allowed_roots):
        raise PermissionError("Batch transcription folder is outside runtime roots.")
    model = config.get("model", "base")
    language = config.get("language") or None
    output_path = Path(
        config.get("output_dir") or folder_path / "transcripts"
    ).expanduser().resolve(strict=False)
    if not _is_within_allowed_roots(output_path, allowed_roots):
        raise PermissionError("Batch transcription output is outside runtime roots.")
    folder = str(folder_path)
    output_dir = str(output_path)
    videos = sorted(
        str(path)
        for item in folder_path.iterdir()
        if item.is_file()
        and item.suffix.lower() in VIDEO_EXTENSIONS
        and _is_within_allowed_roots(
            path := item.resolve(strict=False), allowed_roots
        )
    ) if folder_path.is_dir() else []
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("批量转录功能不可用：未安装 faster-whisper。") from exc
    os.makedirs(output_dir, exist_ok=True)
    whisper = WhisperModel(model)
    total = len(videos)
    outputs = []
    for index, video in enumerate(videos, start=1):
        if sink.cancelled:
            return {"status": "cancelled", "files": outputs}
        name = os.path.basename(video)
        sink.emit("tool.started", {
            "tool_call_id": str(index), "name": "transcribe", "file": name,
        })
        segments, info = whisper.transcribe(video, language=language)
        target = os.path.join(output_dir, f"{Path(video).stem}.txt")
        with open(target, "w", encoding="utf-8") as handle:
            for segment in segments:
                handle.write(segment.text.strip() + "\n")
        outputs.append(target)
        if hasattr(sink, "create_artifact"):
            sink.create_artifact(
                kind="transcript",
                filename=Path(target).name,
                content=Path(target).read_bytes(),
                mime_type="text/plain; charset=utf-8",
                metadata={"source_file": name, "language": info.language},
            )
        sink.emit("tool.completed", {
            "tool_call_id": str(index), "name": "transcribe", "file": name,
            "output": target, "language": info.language,
        })
        sink.emit("progress.updated", {"current": index, "total": total})
    return {"status": "completed", "files": outputs}


def execute_agent_completion(run_payload, sink):
    """Execute a snapshotted Agent definition as a durable Run."""
    from apps.enterprise.models import Organization
    from core.llm.factory import build_agent_engine

    snapshot = dict(run_payload.get("definition_snapshot") or {})
    definition = dict(snapshot.get("agent_definition") or {})
    model_config = dict(definition.get("model_config") or {})
    organization = Organization.objects.get(pk=run_payload["organization_id"])
    engine = build_agent_engine(
        organization,
        model_config.get("model", ""),
        adapter_name=model_config.get("adapter", ""),
        working_directory=str((run_payload.get("input") or {}).get("working_directory") or ""),
    )
    input_data = dict(run_payload.get("input") or {})
    checkpoint = ((run_payload.get("checkpoint") or {}).get("metadata") or {}).get(
        "checkpoint"
    ) or {}
    messages = checkpoint.get("messages")
    if not isinstance(messages, list):
        history = input_data.get("messages")
        if not isinstance(history, list):
            history = [{
                "role": "user",
                "content": str(input_data.get("message") or input_data),
            }]
        messages = [
            {"role": "system", "content": str(definition.get("system_prompt") or "")},
            *history,
        ]

    resume_command = run_payload.get("resume_command") or {}
    governance = snapshot.get("governance") or {}
    approval_decision = ""
    if resume_command:
        command_type = resume_command.get("type")
        command_payload = resume_command.get("payload") or {}
        if command_type == "answer":
            answer = command_payload.get("text")
            if not answer:
                answer = ", ".join(command_payload.get("selections") or [])
            messages = [*messages, {"role": "user", "content": str(answer or "")}]
        elif command_type == "grant_permission":
            approval_decision = "grant"
        elif command_type == "deny_permission":
            approval_decision = "deny"
            messages = [
                *messages,
                {"role": "user", "content": "The requested permission was denied."},
            ]

    response = engine.complete(
        messages,
        approval_decision=approval_decision,
        require_tool_approval=bool(governance.get("require_tool_approval", False)),
    )
    if response.input_request:
        request = dict(response.input_request)
        input_kind = request.pop("input_kind", "answer")
        sink.request_input(
            input_kind=input_kind,
            request_payload=request,
            checkpoint={"messages": messages},
            expires_in_seconds=int(request.pop("expires_in_seconds", 86400)),
        )
    if not response.success:
        raise RuntimeError(response.error or "Agent execution failed")
    sink.emit("output.delta", {"text": response.content})
    output = {
        "result": response.content,
        "model": response.model,
        "usage": response.usage.model_dump(),
    }
    sink.emit("output.snapshot", output)
    return output


class _WorkflowSink:
    def __init__(self, sink, step):
        self._sink = sink
        self._step = step

    @property
    def cancelled(self):
        return self._sink.cancelled

    def emit(self, event_type, payload):
        self._sink.emit(event_type, {
            "workflow_step_id": self._step["id"],
            "workflow_step_key": self._step["key"],
            "workflow_step_name": self._step["name"],
            **dict(payload or {}),
        })


def _value_at_path(value, path):
    for segment in str(path or "").split("."):
        if not segment:
            continue
        if not isinstance(value, dict) or segment not in value:
            return None, False
        value = value[segment]
    return value, True


def _condition_matches(condition, workflow_input, results):
    if not condition:
        return True
    if condition.get("source") == "dependency":
        source = results.get(condition.get("step"), {}).get("output", {})
    else:
        source = workflow_input
    actual, exists = _value_at_path(source, condition.get("path", ""))
    operator = condition.get("operator", "truthy")
    expected = condition.get("value")
    if operator == "exists":
        return exists
    if operator == "truthy":
        return bool(actual) if exists else False
    if operator == "equals":
        return exists and actual == expected
    if operator == "not_equals":
        return not exists or actual != expected
    if operator == "in":
        return exists and isinstance(expected, list) and actual in expected
    raise RuntimeError(f"Unsupported workflow condition operator: {operator}")


def _validate_workflow_steps(steps):
    by_key = {step["key"]: step for step in steps}
    if len(by_key) != len(steps):
        raise RuntimeError("Workflow snapshot contains duplicate step keys")
    unknown_dependencies = {
        dependency
        for step in steps
        for dependency in (step.get("depends_on") or [])
        if dependency not in by_key
    }
    if unknown_dependencies:
        raise RuntimeError(
            f"Workflow snapshot contains unknown dependencies: {sorted(unknown_dependencies)}"
        )
    return by_key


def _load_workflow_adapter(step, settings):
    entrypoint = settings.EXECUTION_CHILD_ADAPTERS.get(
        step["executor_kind"], {}
    ).get(step["executor_key"])
    if not entrypoint or step["executor_kind"] == "workflow":
        raise RuntimeError(
            f"Workflow step executor is unavailable: {step['executor_kind']}/{step['executor_key']}"
        )
    module_name, attribute_name = entrypoint.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute_name)


def _execute_workflow_step(step, run_payload, workflow_input, dependency_results, sink, settings):
    adapter = _load_workflow_adapter(step, settings)
    definition_snapshot = dict(step)
    dependencies = (step.get("content") or {}).get("dependencies") or {}
    default_agents = [
        value for value in dependencies.get("agents", []) if value.get("is_default")
    ]
    if default_agents:
        definition_snapshot["agent_definition"] = default_agents[0].get("definition") or {}
    step_sink = _WorkflowSink(sink, step)
    max_attempts = int(step.get("max_attempts") or 1)
    for attempt_no in range(1, max_attempts + 1):
        if sink.cancelled:
            return {"status": "cancelled"}
        step_sink.emit("workflow.step.started", {
            "attempt_no": attempt_no,
            "max_attempts": max_attempts,
        })
        try:
            output = adapter({
                **run_payload,
                "definition_snapshot": definition_snapshot,
                "effective_config": step.get("effective_config") or {},
                "input": {
                    **workflow_input,
                    "dependency_outputs": {
                        key: value.get("output", {})
                        for key, value in dependency_results.items()
                    },
                },
            }, step_sink) or {}
            step_sink.emit("workflow.step.completed", {
                "attempt_no": attempt_no,
                "output": output,
            })
            return {"status": "completed", "attempts": attempt_no, "output": output}
        except Exception as exc:
            retrying = attempt_no < max_attempts
            step_sink.emit("workflow.step.failed", {
                "attempt_no": attempt_no,
                "error": str(exc)[:1000],
                "retrying": retrying,
            })
            if not retrying:
                raise
    raise RuntimeError(f"Workflow step exhausted attempts: {step['key']}")


def _durable_step_snapshot(step, governance):
    content = step.get("content") or {}
    snapshot = {
        "application_id": str(step.get("application_id") or ""),
        "application_revision_id": str(step.get("application_revision_id") or ""),
        "application_content_hash": str(step.get("application_content_hash") or ""),
        "content": content,
        "effective_config": step.get("effective_config") or {},
        "governance": governance,
        "workflow_step_id": str(step["id"]),
        "workflow_step_key": step["key"],
    }
    dependencies = content.get("dependencies") or {}
    default_agents = [
        value for value in dependencies.get("agents", []) if value.get("is_default")
    ]
    if default_agents:
        snapshot["agent_definition"] = default_agents[0].get("definition") or {}
    return snapshot


def _load_root_run(run_payload):
    from modules.execution.models import Run

    return Run.objects.select_related("owner", "organization").get(
        pk=run_payload["run_id"]
    )


def _create_or_load_step_run(root, step, workflow_input, dependency_results, governance):
    from django.db import transaction
    from modules.execution.application.runs import create_run
    from modules.execution.models import Run

    with transaction.atomic():
        locked_root = Run.objects.select_for_update().select_related(
            "owner", "organization"
        ).get(pk=root.id)
        child = Run.objects.filter(parent=locked_root, node_key=step["key"]).first()
        if child is not None:
            return child, False
        retry_policy = (step.get("content") or {}).get("retry_policy") or {}
        child = create_run(
            organization=locked_root.organization,
            owner=locked_root.owner,
            parent=locked_root,
            node_key=step["key"],
            executor_kind=step["executor_kind"],
            executor_key=step["executor_key"],
            source_type="workflow_step",
            source_id=step["id"],
            definition_snapshot=_durable_step_snapshot(step, governance),
            input_data={
                **workflow_input,
                "dependency_outputs": {
                    key: value.get("output", {})
                    for key, value in dependency_results.items()
                },
            },
            priority=locked_root.priority,
            max_attempts=int(step.get("max_attempts") or 1),
            retry_safe=bool(retry_policy.get("retry_safe", True)),
        )
        return child, True


def _forward_resume_to_child(root, run_payload):
    from modules.execution.application.commands import submit_run_command
    from modules.execution.models import Run

    checkpoint = ((run_payload.get("checkpoint") or {}).get("metadata") or {}).get(
        "checkpoint"
    ) or {}
    child_id = checkpoint.get("workflow_child_run_id")
    command = run_payload.get("resume_command") or {}
    if not child_id or not command:
        return
    child = Run.objects.filter(pk=child_id, parent=root).first()
    if child is None or child.status != Run.Status.WAITING_INPUT:
        return
    submit_run_command(
        run_id=child.id,
        organization_id=root.organization_id,
        actor=root.owner,
        command_type=command["type"],
        idempotency_key=f"workflow-resume:{root.id}:{command['id']}",
        payload=command.get("payload") or {},
        input_request_id=child.pending_input_request_id,
    )


def _cancel_children(root):
    from modules.execution.application.commands import submit_run_command
    from modules.execution.models import Run, RunCommand

    active = root.child_runs.filter(status__in=(
        Run.Status.QUEUED, Run.Status.RUNNING, Run.Status.WAITING_INPUT,
        Run.Status.CANCELLING,
    ))
    for child in active:
        if child.status == Run.Status.CANCELLING:
            continue
        submit_run_command(
            run_id=child.id,
            organization_id=root.organization_id,
            actor=root.owner,
            command_type=RunCommand.Type.CANCEL,
            idempotency_key=f"workflow-cancel:{root.id}:{child.id}",
            payload={"reason": "parent_cancelled"},
        )


def _wait_for_step_runs(root, children, sink, organization_id, poll_interval=0.25):
    from django.utils import timezone
    from modules.execution.models import Run
    from modules.tenancy.database import tenant_database_context

    pending = dict(children)
    results = {}
    while pending:
        with tenant_database_context(organization_id):
            if sink.cancelled:
                root.refresh_from_db(fields=("status",))
                if root.status == Run.Status.CANCELLING:
                    _cancel_children(root)
                return None
            for key, child_id in list(pending.items()):
                child = Run.objects.get(pk=child_id)
                if child.status == Run.Status.WAITING_INPUT:
                    event = child.events.filter(type="input.required").order_by(
                        "-sequence"
                    ).first()
                    request = dict(event.payload if event else {})
                    input_kind = request.pop("input_kind", child.pending_input_kind)
                    request.pop("input_request_id", None)
                    sink.request_input(
                        input_kind=input_kind,
                        request_payload=request,
                        checkpoint={"workflow_child_run_id": str(child.id)},
                        expires_in_seconds=max(
                            60,
                            int((child.pending_input_expires_at - timezone.now()).total_seconds()),
                        ),
                    )
                if child.status == Run.Status.SUCCEEDED:
                    results[key] = {
                        "status": "completed",
                        "attempts": child.attempt_count,
                        "output": child.output_summary,
                        "child_run_id": str(child.id),
                    }
                    pending.pop(key)
                elif child.status in (Run.Status.FAILED, Run.Status.CANCELLED):
                    raise RuntimeError(
                        f"Workflow step {key} {child.status}: "
                        f"{child.error_message or child.error_code}"
                    )
        if pending:
            time.sleep(poll_interval)
    return results


def _execute_workflow_durable(run_payload, sink):
    from django.conf import settings
    from modules.tenancy.database import tenant_database_context

    steps = list((run_payload.get("definition_snapshot") or {}).get("workflow_steps") or [])
    by_key = _validate_workflow_steps(steps)
    workflow_input = dict(run_payload.get("input") or {})
    governance = (run_payload.get("definition_snapshot") or {}).get("governance") or {}
    results = {}
    pending = set(by_key)
    completed = 0
    max_parallelism = max(1, int(getattr(
        settings, "EXECUTION_WORKFLOW_MAX_PARALLELISM", 4
    )))
    organization_id = run_payload["organization_id"]
    with tenant_database_context(organization_id):
        root = _load_root_run(run_payload)
        _forward_resume_to_child(root, run_payload)
    while pending:
        ready = sorted(
            key for key in pending
            if set(by_key[key].get("depends_on") or []).issubset(results)
        )
        if not ready:
            raise RuntimeError("Workflow snapshot contains a dependency cycle")
        runnable = []
        for key in ready:
            step = by_key[key]
            if _condition_matches(step.get("condition") or {}, workflow_input, results):
                runnable.append(key)
            else:
                results[key] = {"status": "skipped", "attempts": 0, "output": {}}
                _WorkflowSink(sink, step).emit(
                    "workflow.step.skipped", {"condition": step.get("condition") or {}}
                )
                pending.remove(key)
                completed += 1
        runnable = runnable[:max_parallelism]
        children = {}
        for key in runnable:
            step = by_key[key]
            dependencies = {
                dependency: results[dependency]
                for dependency in step.get("depends_on") or []
            }
            with tenant_database_context(organization_id):
                child, _created = _create_or_load_step_run(
                    root, step, workflow_input, dependencies, governance
                )
            children[key] = child.id
            _WorkflowSink(sink, step).emit("workflow.step.started", {
                "child_run_id": str(child.id),
                "status": child.status,
                "max_attempts": child.max_attempts,
            })
        layer_results = _wait_for_step_runs(
            root, children, sink, organization_id
        )
        if layer_results is None:
            return {"status": "cancelled", "steps": []}
        for key, result in layer_results.items():
            results[key] = result
            pending.remove(key)
            completed += 1
            _WorkflowSink(sink, by_key[key]).emit(
                "workflow.step.completed", result
            )
            sink.emit("progress.updated", {"current": completed, "total": len(steps)})
    return {
        "status": "completed",
        "steps": [
            {"step_id": step["id"], "step_key": step["key"], **results[step["key"]]}
            for step in steps
        ],
    }


def _execute_workflow_inline(run_payload, sink):
    """Execute legacy in-memory fixtures; production definitions use child Runs."""
    from django.conf import settings

    steps = list((run_payload.get("definition_snapshot") or {}).get("workflow_steps") or [])
    by_key = _validate_workflow_steps(steps)

    workflow_input = dict(run_payload.get("input") or {})
    results = {}
    pending = set(by_key)
    completed = 0
    max_parallelism = max(
        1, int(getattr(settings, "EXECUTION_WORKFLOW_MAX_PARALLELISM", 4))
    )
    while pending:
        if sink.cancelled:
            break
        ready = sorted(
            key for key in pending
            if set(by_key[key].get("depends_on") or []).issubset(results)
        )
        if not ready:
            raise RuntimeError("Workflow snapshot contains a dependency cycle")

        runnable = []
        for key in ready:
            step = by_key[key]
            dependencies = {
                dependency: results[dependency]
                for dependency in step.get("depends_on") or []
            }
            if _condition_matches(step.get("condition") or {}, workflow_input, results):
                runnable.append((key, step, dependencies))
            else:
                results[key] = {"status": "skipped", "attempts": 0, "output": {}}
                _WorkflowSink(sink, step).emit("workflow.step.skipped", {
                    "condition": step.get("condition") or {},
                })
                pending.remove(key)
                completed += 1
                sink.emit("progress.updated", {"current": completed, "total": len(steps)})

        failures = []
        with ThreadPoolExecutor(max_workers=min(max_parallelism, max(1, len(runnable)))) as pool:
            futures = {
                pool.submit(
                    _execute_workflow_step,
                    step,
                    run_payload,
                    workflow_input,
                    dependencies,
                    sink,
                    settings,
                ): key
                for key, step, dependencies in runnable
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as exc:
                    failures.append((key, exc))
                pending.remove(key)
                completed += 1
                sink.emit("progress.updated", {"current": completed, "total": len(steps)})
        if failures:
            key, error = failures[0]
            raise RuntimeError(f"Workflow step {key} failed: {error}") from error

    ordered_results = [
        {"step_id": step["id"], "step_key": step["key"], **results[step["key"]]}
        for step in steps
        if step["key"] in results
    ]
    status = "cancelled" if sink.cancelled else "completed"
    return {"status": status, "steps": ordered_results}


def execute_workflow(run_payload, sink):
    """Execute a DAG using durable child Runs when requested by its snapshot."""
    snapshot = run_payload.get("definition_snapshot") or {}
    if snapshot.get("durable_children"):
        return _execute_workflow_durable(run_payload, sink)
    return _execute_workflow_inline(run_payload, sink)

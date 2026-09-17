"""Platform adapters for the unified durable execution plane."""

import json

from modules.catalog.guided_prompts import compose_guided_prompt


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
        "workflow_step_name": step["name"],
    }
    if step.get("conversation_id"):
        snapshot["conversation_id"] = str(step["conversation_id"])
    if step.get("application_draft_id"):
        snapshot.update({
            "application_draft_id": str(step["application_draft_id"]),
            "application_draft_version": step.get("application_draft_version"),
        })
    dependencies = content.get("dependencies") or {}
    default_agents = [
        value for value in dependencies.get("agents", []) if value.get("is_default")
    ]
    if default_agents:
        snapshot["agent_definition"] = default_agents[0].get("definition") or {}
    return snapshot


def _resolve_automation_value(binding, workflow_input, dependency_results):
    """Resolve a declarative workflow input binding for a chat prompt answer."""
    if not isinstance(binding, dict):
        return binding
    if "value" in binding:
        return binding["value"]
    source = str(binding.get("from") or "")
    if source.startswith("workflow.input."):
        value, exists = _value_at_path(
            workflow_input, source.removeprefix("workflow.input.")
        )
        return value if exists else None
    if source.startswith("steps."):
        remainder = source.removeprefix("steps.")
        step_key, separator, path = remainder.partition(".output")
        if separator and step_key in dependency_results:
            value, exists = _value_at_path(
                dependency_results[step_key].get("output", {}), path.lstrip(".")
            )
            return value if exists else None
    raise RuntimeError(f"Unsupported workflow input binding: {source or binding}")


def _resolve_workflow_outputs(output_mapping, results):
    """Project step outputs into the workflow's stable result contract."""
    outputs = {
        key: value.get("output", {})
        for key, value in results.items()
    }
    if not output_mapping:
        return outputs
    projected = {}
    for name, binding in output_mapping.items():
        if isinstance(binding, str):
            binding = {"from": binding}
        if not isinstance(binding, dict) or "from" not in binding:
            projected[name] = binding
            continue
        source = str(binding["from"])
        if not source.startswith("steps."):
            raise RuntimeError(f"Unsupported workflow output binding: {source}")
        remainder = source.removeprefix("steps.")
        step_key, separator, path = remainder.partition(".output")
        if not separator or step_key not in results:
            projected[name] = None
            continue
        value, exists = _value_at_path(
            results[step_key].get("output", {}), path.lstrip(".")
        )
        projected[name] = value if exists else None
    return projected


def _render_step_message(step, workflow_input, dependency_results):
    """Render a chat application's guided prompt for unattended execution."""
    content = step.get("content") or {}
    prompts = content.get("guided_prompts") or []
    if not prompts:
        return ""
    effective_config = step.get("effective_config") or {}
    automation = effective_config.get("automation") or {}
    prompt_key = (
        automation.get("guided_prompt_key")
        or effective_config.get("guided_entry_prompt_key")
        or (content.get("default_config") or {}).get("guided_entry_prompt_key")
    )
    prompt = next(
        (
            item for item in prompts
            if str(item.get("id") or item.get("key")) == str(prompt_key)
        ),
        prompts[0] if not prompt_key else None,
    )
    if prompt is None:
        raise RuntimeError(
            f"Workflow step {step['key']} references unknown guided prompt {prompt_key}"
        )

    configured_answers = automation.get("answers") or {}
    if not isinstance(configured_answers, dict):
        raise RuntimeError(
            f"Workflow step {step['key']} automation.answers must be an object"
        )
    answers = {
        question["key"]: workflow_input.get(question["key"])
        for question in prompt.get("questions", [])
        if question.get("key") in workflow_input
    }
    answers.update({
        key: _resolve_automation_value(binding, workflow_input, dependency_results)
        for key, binding in configured_answers.items()
    })
    missing_required_text = [
        question
        for question in prompt.get("questions", [])
        if question.get("required")
        and question.get("type") == "text"
        and answers.get(question["key"], question.get("default_value")) in (None, "")
    ]
    if missing_required_text and dependency_results:
        dependency_outputs = {
            key: value.get("output", {})
            for key, value in dependency_results.items()
        }
        if len(dependency_outputs) == 1:
            dependency_value = next(iter(dependency_outputs.values()))
            if isinstance(dependency_value, dict) and dependency_value.get("result"):
                dependency_value = dependency_value["result"]
        else:
            dependency_value = dependency_outputs
        if not isinstance(dependency_value, str):
            dependency_value = json.dumps(
                dependency_value,
                ensure_ascii=False,
                indent=2,
            )
        preferred_keys = ("source", "article", "content", "input", "text", "material")
        target = next((
            question
            for key in preferred_keys
            for question in missing_required_text
            if question["key"] == key
        ), missing_required_text[0])
        answers[target["key"]] = dependency_value
    rendered = compose_guided_prompt(
        prompt,
        answers,
        application_id=int(step.get("application_id") or 0),
    )
    return rendered["prompt"]


def _load_root_run(run_payload):
    from modules.execution.models import Run

    return Run.objects.select_related("owner", "organization").get(
        pk=run_payload["run_id"]
    )


def _create_step_conversation(root, step, working_directory):
    """Create a chat step's Conversation only when its child Run is runnable."""

    content = step.get("content") or {}
    if content.get("kind") != "chat":
        return step
    from apps.conversations.models import Conversation

    default_agent = next((
        item
        for item in (content.get("dependencies") or {}).get("agents", [])
        if item.get("is_default")
    ), None)
    workflow_name = str(
        (root.definition_snapshot or {}).get("workflow_name") or "Workflow"
    )
    conversation = Conversation.objects.create(
        user=root.owner,
        organization=root.organization,
        title=f"{workflow_name} · {step['name']}",
        agent_id=(default_agent or {}).get("agent_id"),
        chat_application_id=step.get("application_id"),
        process_id=f"workflow:{step['key']}"[:64],
        working_directory=str(working_directory or ""),
    )
    return {**step, "conversation_id": str(conversation.id)}


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
        child_input = {
            **workflow_input,
            **dict(step.get("runtime_input") or {}),
            "dependency_outputs": {
                key: value.get("output", {})
                for key, value in dependency_results.items()
            },
        }
        # The root Run owns the workspace. Every workflow Agent receives the
        # same directory so files produced by dependent steps are immediately
        # available to the steps that follow. Runtime step input must not be
        # able to replace this server-controlled path.
        if workflow_input.get("working_directory"):
            child_input["working_directory"] = workflow_input["working_directory"]
        message = _render_step_message(step, workflow_input, dependency_results)
        if message:
            child_input["message"] = message
        step_snapshot = _create_step_conversation(
            locked_root,
            step,
            child_input.get("working_directory"),
        )
        child = create_run(
            organization=locked_root.organization,
            owner=locked_root.owner,
            parent=locked_root,
            node_key=step_snapshot["key"],
            executor_kind=step_snapshot["executor_kind"],
            executor_key=step_snapshot["executor_key"],
            source_type="workflow_step",
            source_id=step_snapshot["id"],
            definition_snapshot=_durable_step_snapshot(step_snapshot, governance),
            input_data=child_input,
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
        Run.Status.WAITING_CHILDREN, Run.Status.CANCELLING,
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


def _completed_step_result(child):
    result = {
        "status": "completed",
        "attempts": child.attempt_count,
        "output": child.output_summary,
        "child_run_id": str(child.id),
    }
    conversation_id = (child.definition_snapshot or {}).get("conversation_id")
    if conversation_id:
        result["conversation_id"] = str(conversation_id)
    return result


def _wait_for_step_runs(root, children, sink, organization_id, poll_interval=None):
    """Collect completed children or durably release the workflow Worker.

    ``poll_interval`` remains as a compatibility argument for custom adapters;
    the durable workflow no longer sleeps while its children execute.
    """

    from django.utils import timezone
    from modules.execution.models import Run
    from modules.tenancy.database import tenant_database_context

    results = {}
    active_ids = []
    with tenant_database_context(organization_id):
        if sink.cancelled:
            root.refresh_from_db(fields=("status",))
            if root.status == Run.Status.CANCELLING:
                _cancel_children(root)
            return None
        for key, child_id in children.items():
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
                results[key] = _completed_step_result(child)
            elif child.status in (Run.Status.FAILED, Run.Status.CANCELLED):
                sink.emit("workflow.step.failed", {
                    "workflow_step_key": key,
                    "child_run_id": str(child.id),
                    "status": child.status,
                    "error_code": child.error_code,
                    "error_message": child.error_message,
                })
                raise RuntimeError(
                    f"Workflow step {key} {child.status}: "
                    f"{child.error_message or child.error_code}"
                )
            else:
                active_ids.append(child.id)
    if active_ids:
        sink.wait_for_children(
            child_run_ids=active_ids,
            checkpoint={"workflow_child_run_ids": [str(value) for value in active_ids]},
        )
    return results


def _execute_workflow_durable(run_payload, sink):
    from django.conf import settings
    from modules.execution.models import Run
    from modules.tenancy.database import tenant_database_context

    steps = list((run_payload.get("definition_snapshot") or {}).get("workflow_steps") or [])
    by_key = _validate_workflow_steps(steps)
    workflow_input = dict(run_payload.get("input") or {})
    governance = (run_payload.get("definition_snapshot") or {}).get("governance") or {}
    results = dict(
        (run_payload.get("definition_snapshot") or {}).get("initial_results") or {}
    )
    max_parallelism = max(1, int(getattr(
        settings, "EXECUTION_WORKFLOW_MAX_PARALLELISM", 4
    )))
    organization_id = run_payload["organization_id"]
    with tenant_database_context(organization_id):
        root = _load_root_run(run_payload)
        _forward_resume_to_child(root, run_payload)
        emitted = {
            event_type: set(
                root.events.filter(type=event_type).values_list(
                    "payload__workflow_step_key", flat=True
                )
            )
            for event_type in (
                "workflow.step.completed",
                "workflow.step.skipped",
            )
        }
        latest_progress = root.events.filter(
            type="progress.updated"
        ).order_by("-sequence").values_list("payload", flat=True).first() or {}
        for child in root.child_runs.all():
            if child.status in (Run.Status.FAILED, Run.Status.CANCELLED):
                if child.node_key in by_key:
                    _WorkflowSink(sink, by_key[child.node_key]).emit(
                        "workflow.step.failed",
                        {
                            "child_run_id": str(child.id),
                            "status": child.status,
                            "error_code": child.error_code,
                            "error_message": child.error_message,
                        },
                    )
                raise RuntimeError(
                    f"Workflow step {child.node_key} {child.status}: "
                    f"{child.error_message or child.error_code}"
                )
            if child.status == Run.Status.SUCCEEDED:
                result = _completed_step_result(child)
                results[child.node_key] = result
                if child.node_key not in emitted["workflow.step.completed"]:
                    _WorkflowSink(sink, by_key[child.node_key]).emit(
                        "workflow.step.completed", result
                    )
        for key, result in results.items():
            if (
                key in by_key
                and result.get("reused")
                and key not in emitted["workflow.step.completed"]
            ):
                _WorkflowSink(sink, by_key[key]).emit(
                    "workflow.step.completed", result
                )
        for key in emitted["workflow.step.skipped"]:
            if key in by_key:
                results[key] = {"status": "skipped", "attempts": 0, "output": {}}

    last_progress = (
        latest_progress.get("current"), latest_progress.get("total")
    )

    def emit_progress(current):
        nonlocal last_progress
        progress = (current, len(steps))
        if progress == last_progress:
            return
        sink.emit("progress.updated", {
            "current": current,
            "total": len(steps),
        })
        last_progress = progress

    pending = set(by_key) - set(results)
    completed = len(results)
    # Durable workflows suspend their Worker while child Runs execute. Emit
    # progress immediately after rebuilding state on every resume; code after
    # wait_for_children() is not reached when the attempt is suspended.
    emit_progress(completed)
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
                if key not in emitted["workflow.step.skipped"]:
                    _WorkflowSink(sink, step).emit(
                        "workflow.step.skipped", {"condition": step.get("condition") or {}}
                    )
                pending.remove(key)
                completed += 1
                emit_progress(completed)
        runnable = runnable[:max_parallelism]
        children = {}
        for key in runnable:
            step = by_key[key]
            dependencies = {
                dependency: results[dependency]
                for dependency in step.get("depends_on") or []
            }
            with tenant_database_context(organization_id):
                child, created = _create_or_load_step_run(
                    root, step, workflow_input, dependencies, governance
                )
            children[key] = child.id
            if created:
                started = {
                    "child_run_id": str(child.id),
                    "status": child.status,
                    "max_attempts": child.max_attempts,
                }
                conversation_id = (child.definition_snapshot or {}).get(
                    "conversation_id"
                )
                if conversation_id:
                    started["conversation_id"] = str(conversation_id)
                _WorkflowSink(sink, step).emit("workflow.step.started", started)
        layer_results = _wait_for_step_runs(
            root,
            children,
            sink,
            organization_id,
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
            emit_progress(completed)
    outputs = {
        key: value.get("output", {})
        for key, value in results.items()
    }
    return {
        "status": "completed",
        "outputs": outputs,
        "result": _resolve_workflow_outputs(
            (run_payload.get("definition_snapshot") or {}).get("output_mapping") or {},
            results,
        ),
        "steps": [
            {"step_id": step["id"], "step_key": step["key"], **results[step["key"]]}
            for step in steps
        ],
    }


def execute_workflow(run_payload, sink):
    """Execute a DAG exclusively through durable child Runs."""
    snapshot = run_payload.get("definition_snapshot") or {}
    if not snapshot.get("durable_children"):
        raise RuntimeError("Workflow execution requires durable child Runs")
    return _execute_workflow_durable(run_payload, sink)

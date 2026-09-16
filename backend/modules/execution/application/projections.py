"""Project durable Run events into conversation messages."""
import json

from django.db import transaction

from modules.execution.models import Run


def _display_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _segment_start(run, through_sequence):
    return (
        run.events.filter(
            type="input.accepted", sequence__lt=through_sequence,
        ).order_by("-sequence").values_list("sequence", flat=True).first()
        or 0
    )


def _project_tool_calls(run, *, after_sequence=0, through_sequence=None):
    """Build tool lifecycle state for one visible conversation turn."""

    calls = {}
    order = []
    events = run.events.filter(
        type__in=("tool.started", "tool.completed", "tool.failed"),
        sequence__gt=after_sequence,
    )
    if through_sequence is not None:
        events = events.filter(sequence__lte=through_sequence)
    for event in events.order_by("sequence"):
        payload = event.payload or {}
        call_id = str(
            payload.get("tool_call_id") or payload.get("call_id") or event.sequence
        )
        if call_id not in calls:
            calls[call_id] = {
                "id": call_id,
                "name": str(payload.get("name") or payload.get("tool") or "tool"),
                "status": "running",
            }
            order.append(call_id)
        call = calls[call_id]
        if payload.get("name") or payload.get("tool"):
            call["name"] = str(payload.get("name") or payload.get("tool"))
        input_value = _display_value(payload.get("input"))
        if input_value is not None:
            call["input"] = input_value
        result_value = _display_value(payload.get("result", payload.get("output")))
        if result_value is not None:
            call["result"] = result_value
        if event.type == "tool.failed":
            call["status"] = "failed"
            error_message = payload.get("error_message")
            if error_message:
                call["error_message"] = str(error_message)
        elif event.type == "tool.completed":
            call["status"] = "completed"
    return [calls[call_id] for call_id in order]


def _output_segment(run, *, after_sequence, through_sequence):
    output = ""
    events = run.events.filter(
        type__in=("output.delta", "output.snapshot"),
        sequence__gt=after_sequence,
        sequence__lte=through_sequence,
    ).order_by("sequence")
    for event in events:
        payload = event.payload or {}
        if event.type == "output.delta":
            output += str(payload.get("text") or "")
        else:
            value = payload.get("text", payload.get("result", payload.get("output", "")))
            output = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, sort_keys=True
            )
    return output.strip()


def _normalized_questions(payload):
    questions = payload.get("questions")
    if isinstance(questions, list) and questions:
        return [item for item in questions if isinstance(item, dict)]
    return [{
        "id": "question-1",
        "header": payload.get("header") or "",
        "question": payload.get("question") or payload.get("prompt") or "请提供回答",
        "options": payload.get("options") or [],
    }]


def _question_content(payload):
    parts = []
    questions = _normalized_questions(payload)
    for index, question in enumerate(questions):
        header = str(question.get("header") or "").strip()
        text = str(question.get("question") or "请提供回答").strip()
        lines = []
        if header and (len(questions) > 1 or header != "Agent 提问"):
            lines.append(f"**{header}**")
        lines.append(text)
        options = question.get("options") or []
        labels = [
            str(option.get("label") or option.get("value") or "").strip()
            for option in options
            if isinstance(option, dict)
        ]
        labels = [label for label in labels if label]
        if labels:
            lines.append("可选：" + " / ".join(labels))
        prefix = f"{index + 1}. " if len(questions) > 1 else ""
        parts.append(prefix + "\n".join(lines))
    return "\n\n".join(parts)


def _answer_content(command_payload, request_payload):
    command_payload = command_payload or {}
    answers = command_payload.get("answers")
    if isinstance(answers, dict) and answers:
        questions = {
            str(item.get("id") or ""): item
            for item in _normalized_questions(request_payload)
        }
        lines = []
        for question_id, answer_payload in answers.items():
            values = (
                answer_payload.get("answers")
                if isinstance(answer_payload, dict)
                else answer_payload
            ) or []
            if not isinstance(values, list):
                values = [values]
            question = questions.get(str(question_id), {})
            answer = " / ".join(str(value) for value in values)
            if question.get("is_secret") or question.get("isSecret"):
                answer = "••••••"
            label = str(question.get("question") or "").strip()
            lines.append(
                f"{label}：{answer}" if label and len(answers) > 1 else answer
            )
        return "\n".join(lines)
    text = str(command_payload.get("text") or "").strip()
    if text:
        return text
    selections = command_payload.get("selections") or []
    return " / ".join(str(value) for value in selections)


def _conversation_id_for_run(run):
    if run.source_type == "conversation" and run.source_id:
        return run.source_id
    if run.source_type == "workflow_step":
        return (run.definition_snapshot or {}).get("conversation_id")
    return None


def _conversation_for_run(run, Conversation):
    conversation_id = _conversation_id_for_run(run)
    if not conversation_id:
        return None
    return Conversation.objects.select_for_update().filter(
        pk=conversation_id,
        organization_id=run.organization_id,
        user_id=run.owner_id,
    ).first()


def project_input_required(run_id, event):
    """Persist an Agent question as its own assistant conversation turn."""

    run = Run.objects.get(pk=run_id)
    if not _conversation_id_for_run(run):
        return None
    from apps.conversations.models import Conversation, Message

    with transaction.atomic():
        conversation = _conversation_for_run(run, Conversation)
        if conversation is None:
            return None
        payload = event.payload or {}
        start = _segment_start(run, event.sequence)
        output = _output_segment(
            run, after_sequence=start, through_sequence=event.sequence,
        )
        question = _question_content(payload)
        content = "\n\n".join(value for value in (output, question) if value)
        tool_calls = _project_tool_calls(
            run, after_sequence=start, through_sequence=event.sequence,
        )
        metadata = {
            "run_id": str(run.id),
            "run_event_sequence": event.sequence,
            "interaction": {
                "type": "input.required",
                "input_request_id": payload.get("input_request_id"),
                "input_kind": payload.get("input_kind"),
            },
        }
        if tool_calls:
            metadata["agent"] = {"tool_calls": tool_calls}
        message, _ = Message.objects.get_or_create(
            run=run,
            run_event_sequence=event.sequence,
            defaults={
                "conversation": conversation,
                "role": "assistant",
                "content": content,
                "metadata": metadata,
            },
        )
        Message.objects.filter(pk=message.pk).update(created_at=event.created_at)
        message.created_at = event.created_at
        return message


def project_input_accepted(run_id, event, command):
    """Persist an interactive answer as its own user conversation turn."""

    run = Run.objects.get(pk=run_id)
    if not _conversation_id_for_run(run):
        return None
    from apps.conversations.models import Conversation, Message

    with transaction.atomic():
        conversation = _conversation_for_run(run, Conversation)
        if conversation is None:
            return None
        required = run.events.filter(
            type="input.required",
            payload__input_request_id=str(command.input_request_id),
        ).order_by("-sequence").first()
        request_payload = required.payload if required else {}
        if command.type == "grant_permission":
            content = "允许"
        elif command.type == "deny_permission":
            content = "拒绝"
        else:
            content = _answer_content(command.payload, request_payload)
        message, _ = Message.objects.get_or_create(
            run=run,
            run_event_sequence=event.sequence,
            defaults={
                "conversation": conversation,
                "role": "user",
                "content": content,
                "metadata": {
                    "run_id": str(run.id),
                    "run_event_sequence": event.sequence,
                    "interaction": {
                        "type": "input.accepted",
                        "input_request_id": str(command.input_request_id),
                        "command_type": command.type,
                    },
                },
            },
        )
        Message.objects.filter(pk=message.pk).update(created_at=event.created_at)
        message.created_at = event.created_at
        return message


def project_terminal_run(run_id, output):
    run = Run.objects.get(pk=run_id)
    if not _conversation_id_for_run(run):
        return
    from apps.conversations.models import Conversation, Message

    with transaction.atomic():
        conversation = _conversation_for_run(run, Conversation)
        if conversation is None:
            return
        if run.source_type == "workflow_step":
            user_message, _ = Message.objects.get_or_create(
                conversation=conversation,
                run=run,
                role="user",
                run_event_sequence=None,
                defaults={
                    "content": str((run.input or {}).get("message") or ""),
                    "metadata": {
                        "run_id": str(run.id),
                        "workflow_step_key": run.node_key,
                        "automated": True,
                    },
                },
            )
            Message.objects.filter(pk=user_message.pk).update(created_at=run.created_at)
        agent_thread = output.get("agent_thread") or {}
        provider = str(agent_thread.get("provider") or "")
        thread_id = str(agent_thread.get("id") or "")
        if not provider or not thread_id:
            provider = ""
            thread_id = ""
        if (
            conversation.agent_thread_provider != provider
            or conversation.agent_thread_id != thread_id
        ):
            conversation.agent_thread_provider = provider
            conversation.agent_thread_id = thread_id
            conversation.save(update_fields=(
                "agent_thread_provider", "agent_thread_id", "updated_at",
            ))
        start = _segment_start(run, run.next_event_sequence)
        tool_calls = _project_tool_calls(run, after_sequence=start)
        metadata = {
            "run_id": str(run.id),
            "run_event_sequence": run.next_event_sequence,
            "model": output.get("model") or "",
            "usage": output.get("usage") or {},
        }
        agent_metadata = {}
        if tool_calls:
            agent_metadata["tool_calls"] = tool_calls
        loaded_skills = output.get("loaded_skills") or []
        if loaded_skills:
            agent_metadata["loaded_skills"] = loaded_skills
        if agent_metadata:
            metadata["agent"] = agent_metadata
        terminal_event = run.events.filter(
            sequence=run.next_event_sequence,
        ).first()
        legacy_message = Message.objects.filter(
            run=run,
            run_event_sequence__isnull=True,
            role="assistant",
        ).first()
        if legacy_message is not None:
            legacy_message.run_event_sequence = run.next_event_sequence
            legacy_message.metadata = metadata
            legacy_message.save(update_fields=("run_event_sequence", "metadata"))
            if terminal_event is not None:
                Message.objects.filter(pk=legacy_message.pk).update(
                    created_at=terminal_event.created_at,
                )
            return
        message, _ = Message.objects.get_or_create(
            run=run,
            run_event_sequence=run.next_event_sequence,
            defaults={
                "conversation": conversation,
                "role": "assistant",
                "content": str(output.get("result") or ""),
                "metadata": metadata,
            },
        )
        if terminal_event is not None:
            Message.objects.filter(pk=message.pk).update(
                created_at=terminal_event.created_at,
            )


def repair_conversation_messages(conversation):
    """Idempotently rebuild missing chat messages from durable Run history."""

    from modules.execution.models import RunCommand

    runs = Run.objects.for_organization(conversation.organization_id).filter(
        source_type="conversation",
        source_id=str(conversation.id),
        owner_id=conversation.user_id,
    ).order_by("created_at")
    for run in runs:
        for event in run.events.filter(
            type__in=("input.required", "input.accepted"),
        ).order_by("sequence"):
            if event.type == "input.required":
                project_input_required(run.id, event)
                continue
            command_id = (event.payload or {}).get("command_id")
            command = RunCommand.objects.filter(
                pk=command_id,
                run=run,
            ).first() if command_id else None
            if command is not None:
                project_input_accepted(run.id, event, command)
        if run.status == Run.Status.SUCCEEDED and run.output_summary:
            project_terminal_run(run.id, run.output_summary)

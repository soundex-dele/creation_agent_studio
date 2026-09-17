"""Durable fallback executor for structured tutoring operations."""

from .backend.strategies import get_subject_strategy


def execute_study_with_method(run_payload, sink):
    data = {
        **dict(run_payload.get("effective_config") or {}),
        **dict(run_payload.get("input") or {}),
    }
    strategy = get_subject_strategy(str(data.get("subject") or ""))
    problem = str(data.get("problem") or "").strip()
    operation = str(data.get("operation") or "analyze")
    level = int(data.get("hint_level") or 1)
    if not problem:
        raise ValueError("题目内容不能为空。")
    hint = strategy.hint(
        problem,
        4 if operation == "solution" else level,
        str(data.get("student_thought") or ""),
    )
    output = {
        "subject": strategy.subject,
        "recognized_problem": problem,
        "knowledge_points": [strategy.detect_topic(problem)],
        "hint_level": hint["hint_level"],
        "hint": hint["hint"],
        "steps": [],
        "final_answer": "",
        "validation_status": "needs_ai_or_teacher_review",
        "variant_problem": "",
        "variant_answer": "",
        "strategy_version": strategy.version,
    }
    sink.emit("output.snapshot", output)
    return output

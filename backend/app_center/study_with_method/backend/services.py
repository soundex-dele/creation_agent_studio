"""Application services for planning, review scheduling and reporting."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.agents.models import Agent
from apps.conversations.models import Conversation, Message
from modules.execution.application.start_runs import start_agent_run

from .models import (
    Attempt,
    CurriculumNode,
    GradeStage,
    KnowledgeMastery,
    MistakeRecord,
    Problem,
    ReviewSchedule,
    StudyProfile,
    StudyTask,
    Subject,
    SubjectEnrollment,
    WeeklyReport,
    WeeklyQuiz,
)
from .strategies import get_subject_strategy


REVIEW_INTERVALS = (1, 3, 7, 14)
TUTOR_AGENT_SLUG = "study-with-method-tutor"


def monday_for(value):
    return value - timedelta(days=value.weekday())


def active_enrollment(profile: StudyProfile, subject=Subject.MATH):
    return profile.enrollments.filter(subject=subject, is_active=True).first()


def generate_week_plan(profile: StudyProfile, enrollment: SubjectEnrollment):
    today = timezone.localdate()
    weak_topics = enrollment.weak_topics or []
    per_task = max(10, profile.daily_minutes // (3 if weak_topics else 2))
    created = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        rows = [
            (
                StudyTask.Type.SCHOOL_SYNC,
                f"同步巩固：{enrollment.current_chapter}",
                min(30, per_task),
            ),
        ]
        if weak_topics:
            topic = str(weak_topics[offset % len(weak_topics)])
            rows.append((StudyTask.Type.WEAK_POINT, f"薄弱点训练：{topic}", per_task))
        else:
            rows.append((StudyTask.Type.WEAK_POINT, "基础巩固：完成 3 道典型题", per_task))
        if offset == 6:
            rows.append((StudyTask.Type.WEEKLY_QUIZ, "本周数学小测与复盘", per_task))
        for task_type, title, duration in rows:
            task, was_created = StudyTask.objects.get_or_create(
                organization=profile.organization,
                profile=profile,
                subject=enrollment.subject,
                grade_stage=enrollment.grade_stage,
                scheduled_for=day,
                task_type=task_type,
                title=title,
                defaults={"duration_minutes": duration},
            )
            if was_created:
                created.append(task)
    return created


def reschedule_overdue_tasks(profile: StudyProfile):
    today = timezone.localdate()
    overdue = list(
        profile.tasks.filter(
            status=StudyTask.Status.PENDING, scheduled_for__lt=today
        ).order_by("scheduled_for", "created_at")
    )
    for task in overdue:
        task.metadata = {**task.metadata, "rescheduled_from": str(task.scheduled_for)}
        task.scheduled_for = today
        try:
            with transaction.atomic():
                task.save(update_fields=("scheduled_for", "metadata", "updated_at"))
        except IntegrityError:
            task.status = StudyTask.Status.SKIPPED
            task.save(update_fields=("status", "metadata", "updated_at"))


def record_attempt(
    *, problem: Problem, response: str, thought: str, duration_seconds: int, is_correct=None
):
    strategy = get_subject_strategy(problem.subject)
    expected = str((problem.answer_key or {}).get("answer") or "")
    if expected and is_correct is None:
        is_correct = strategy.normalize_answer(response) == strategy.normalize_answer(expected)
    attempt = Attempt.objects.create(
        organization=problem.organization,
        profile=problem.profile,
        problem=problem,
        subject=problem.subject,
        grade_stage=problem.grade_stage,
        response=response,
        student_thought=thought,
        is_correct=is_correct,
        hint_level_used=problem.max_hint_level,
        duration_seconds=duration_seconds,
    )
    if problem.knowledge_point_id:
        mastery, _ = KnowledgeMastery.objects.get_or_create(
            organization=problem.organization,
            profile=problem.profile,
            knowledge_point=problem.knowledge_point,
            defaults={
                "subject": problem.subject,
                "grade_stage": problem.grade_stage,
            },
        )
        mastery.attempts_count += 1
        if is_correct:
            mastery.correct_count += 1
        mastery.score = round(100 * mastery.correct_count / mastery.attempts_count)
        mastery.save(
            update_fields=("attempts_count", "correct_count", "score", "updated_at")
        )
    if is_correct is False:
        mistake, _ = MistakeRecord.objects.get_or_create(
            organization=problem.organization,
            profile=problem.profile,
            problem=problem,
            defaults={
                "subject": problem.subject,
                "grade_stage": problem.grade_stage,
                "knowledge_point": problem.knowledge_point,
            },
        )
        ReviewSchedule.objects.get_or_create(
            organization=problem.organization,
            profile=problem.profile,
            mistake=mistake,
            defaults={
                "subject": problem.subject,
                "grade_stage": problem.grade_stage,
                "next_review_at": timezone.now() + timedelta(days=REVIEW_INTERVALS[0]),
            },
        )
    problem.status = Problem.Status.COMPLETED
    problem.save(update_fields=("status", "updated_at"))
    return attempt


def complete_review(schedule: ReviewSchedule, is_correct: bool):
    schedule.completed_reviews += 1
    schedule.last_result = "correct" if is_correct else "incorrect"
    if is_correct:
        schedule.interval_step = min(schedule.interval_step + 1, len(REVIEW_INTERVALS) - 1)
        schedule.mistake.mastery = min(100, schedule.mistake.mastery + 20)
    else:
        schedule.interval_step = 0
        schedule.mistake.mastery = max(0, schedule.mistake.mastery - 10)
    schedule.next_review_at = timezone.now() + timedelta(
        days=REVIEW_INTERVALS[schedule.interval_step]
    )
    schedule.mistake.save(update_fields=("mastery", "updated_at"))
    schedule.save(
        update_fields=(
            "completed_reviews",
            "last_result",
            "interval_step",
            "next_review_at",
            "updated_at",
        )
    )
    return schedule


def build_weekly_report(profile: StudyProfile, enrollment: SubjectEnrollment):
    today = timezone.localdate()
    week_start = monday_for(today)
    week_end = week_start + timedelta(days=7)
    tasks = profile.tasks.filter(
        subject=enrollment.subject,
        scheduled_for__gte=week_start,
        scheduled_for__lt=week_end,
    )
    totals = tasks.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status=StudyTask.Status.COMPLETED)),
        planned_minutes=Sum("duration_minutes"),
    )
    attempts = profile.attempts.filter(
        subject=enrollment.subject,
        created_at__date__gte=week_start,
        created_at__date__lt=week_end,
    )
    attempt_total = attempts.count()
    correct = attempts.filter(is_correct=True).count()
    due_reviews = profile.review_schedules.filter(
        subject=enrollment.subject, next_review_at__lte=timezone.now()
    ).count()
    total = totals["total"] or 0
    completed = totals["completed"] or 0
    metrics = {
        "task_total": total,
        "task_completed": completed,
        "completion_rate": round(100 * completed / total) if total else 0,
        "planned_minutes": totals["planned_minutes"] or 0,
        "attempt_total": attempt_total,
        "correct_rate": round(100 * correct / attempt_total) if attempt_total else 0,
        "mistake_count": profile.mistakes.filter(subject=enrollment.subject).count(),
        "due_review_count": due_reviews,
    }
    report, _ = WeeklyReport.objects.update_or_create(
        organization=profile.organization,
        profile=profile,
        subject=enrollment.subject,
        grade_stage=enrollment.grade_stage,
        week_start=week_start,
        defaults={
            "metrics": metrics,
            "summary": (
                f"本周完成 {completed}/{total} 项学习任务，"
                f"练习正确率 {metrics['correct_rate']}%。"
            ),
            "next_week_advice": (
                f"下周继续跟进“{enrollment.current_chapter}”，"
                "优先完成到期错题复习，再进行新题训练。"
            ),
        },
    )
    return report


def build_weekly_quiz(profile: StudyProfile, enrollment: SubjectEnrollment):
    mistakes = list(
        profile.mistakes.filter(subject=enrollment.subject)
        .select_related("problem", "knowledge_point")
        .order_by("mastery", "-updated_at")[:5]
    )
    if not mistakes:
        raise ValueError("至少记录一道错题后才能生成周测。")
    questions = [
        {
            "id": str(uuid.uuid4()),
            "prompt": mistake.problem.confirmed_text or mistake.problem.original_text,
            "knowledge_point": (
                mistake.knowledge_point.code if mistake.knowledge_point else ""
            ),
            "source_problem_id": str(mistake.problem_id),
            "validation_status": "source_problem_confirmed",
        }
        for mistake in mistakes
    ]
    quiz, _ = WeeklyQuiz.objects.update_or_create(
        organization=profile.organization,
        profile=profile,
        subject=enrollment.subject,
        grade_stage=enrollment.grade_stage,
        week_start=monday_for(timezone.localdate()),
        defaults={
            "questions": questions,
            "results": {},
            "status": WeeklyQuiz.Status.READY,
            "score": None,
            "completed_at": None,
        },
    )
    return quiz


def submit_weekly_quiz(quiz: WeeklyQuiz, answers: list[dict]):
    known = {str(question["id"]) for question in quiz.questions}
    provided = {str(answer.get("question_id") or "") for answer in answers}
    if known != provided:
        raise ValueError("请完成周测中的全部题目。")
    if not all(isinstance(answer.get("is_correct"), bool) for answer in answers):
        raise ValueError("每道题都必须标记作答结果。")
    correct = sum(bool(answer["is_correct"]) for answer in answers)
    quiz.results = {
        "answers": [
            {
                "question_id": str(answer["question_id"]),
                "is_correct": bool(answer["is_correct"]),
            }
            for answer in answers
        ],
        "correct": correct,
        "total": len(known),
    }
    quiz.score = round(100 * correct / len(known)) if known else 0
    quiz.status = WeeklyQuiz.Status.COMPLETED
    quiz.completed_at = timezone.now()
    quiz.save(
        update_fields=("results", "score", "status", "completed_at", "updated_at")
    )
    quiz.profile.tasks.filter(
        subject=quiz.subject,
        task_type=StudyTask.Type.WEEKLY_QUIZ,
        scheduled_for__gte=quiz.week_start,
        scheduled_for__lt=quiz.week_start + timedelta(days=7),
    ).update(status=StudyTask.Status.COMPLETED, completed_at=timezone.now())
    return quiz


def start_tutor_run(*, problem: Problem, actor, operation: str, student_thought="", hint_level=1):
    agent = Agent.objects.filter(
        organization=problem.organization,
        slug=TUTOR_AGENT_SLUG,
        is_active=True,
    ).first()
    if agent is None:
        return None
    prompt = problem.confirmed_text or problem.original_text
    image_path = ""
    image_directory = ""
    if problem.source_image:
        try:
            image_path = problem.source_image.path
            image_directory = str(Path(image_path).parent)
        except NotImplementedError:
            image_path = problem.source_image.url
    problem_source = prompt or (
        f"题目图片路径：{image_path}。请先读取图片并准确转写题目。"
    )
    message = (
        "请严格按系统提示，以 JSON 对象完成学习辅导。\n"
        f"operation: {operation}\nsubject: {problem.subject}\n"
        f"grade_stage: {problem.grade_stage}\nhint_level: {hint_level}\n"
        f"problem: {problem_source}\nstudent_thought: {student_thought}"
    )
    operation_messages = {
        "analyze": (
            f"请识别并分析这道数学题：\n{prompt}"
            if prompt else "请识别并分析我上传的这道数学题。"
        ),
        "hint": (
            f"我的思路：{student_thought.strip()}\n请给我第 {hint_level} 级提示。"
            if student_thought.strip() else f"请给我第 {hint_level} 级提示。"
        ),
        "solution": "请给出这道题的完整解析，并说明关键步骤和检查方法。",
        "variant": "请生成一道同知识点、相近难度的变式题，并独立校验答案。",
    }
    visible_message = operation_messages.get(operation, f"请继续辅导这道题：{operation}")

    with transaction.atomic():
        locked_problem = Problem.objects.select_for_update().select_related(
            "conversation"
        ).get(pk=problem.pk)
        conversation = locked_problem.conversation
        if conversation is None:
            title_source = " ".join(prompt.split())[:48] if prompt else "图片题目"
            conversation = Conversation.objects.create(
                user=actor,
                organization=problem.organization,
                title=f"学之有道 · {title_source}",
                agent=agent,
                process_id=f"study-problem:{problem.id}",
            )
            locked_problem.conversation = conversation

        history = list(
            conversation.messages.order_by("created_at", "id").values("role", "content")
        )[-99:]
        history.append({"role": "user", "content": message})
        run, replayed = start_agent_run(
            organization_id=problem.organization_id,
            agent_id=agent.id,
            actor=actor,
            input_data={
                "message": message,
                "messages": history,
                **({"working_directory": image_directory} if image_directory else {}),
                **({
                    "agent_thread": {
                        "provider": conversation.agent_thread_provider,
                        "id": conversation.agent_thread_id,
                    }
                } if conversation.agent_thread_id else {}),
            },
            idempotency_key=f"study-{problem.id}-{operation}-{hint_level}-{uuid.uuid4()}",
            source_type="conversation",
            source_id=str(conversation.id),
            allow_draft=True,
        )
        if not replayed:
            Message.objects.create(
                conversation=conversation,
                role="user",
                content=visible_message,
                metadata={
                    "run_id": str(run.id),
                    "study_with_method": {
                        "problem_id": str(problem.id),
                        "operation": operation,
                        "hint_level": hint_level,
                    },
                },
            )
            conversation.save(update_fields=("updated_at",))
        locked_problem.latest_run_id = run.id
        locked_problem.save(update_fields=(
            "conversation", "latest_run_id", "updated_at",
        ))
        problem.conversation_id = conversation.id
        problem.latest_run_id = run.id
    return run


def resolve_curriculum_node(subject: str, code: str | None):
    if not code:
        return None
    return CurriculumNode.objects.filter(subject=subject, code=code).first()

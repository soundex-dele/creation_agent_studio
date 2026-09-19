"""Application services for planning, review scheduling and reporting."""

from __future__ import annotations

import uuid
from datetime import timedelta
from itertools import cycle
from pathlib import Path

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.agents.models import Agent
from apps.agents.high_school_tutors import TUTOR_DEFINITION_BY_SUBJECT
from apps.conversations.models import Conversation, Message
from apps.conversations.services import attach_existing_image
from modules.execution.application.start_runs import start_agent_run

from .models import (
    AnswerCard,
    Attempt,
    CurriculumNode,
    GradeStage,
    KnowledgeMastery,
    MistakeCheckIn,
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
from .teaching_data import get_knowledge_point


REVIEW_INTERVALS = (1, 3, 7, 14)
TUTOR_AGENT_SLUG = "study-with-method-tutor"


def monday_for(value):
    return value - timedelta(days=value.weekday())


def active_enrollment(profile: StudyProfile, subject=Subject.MATH):
    return profile.enrollments.filter(subject=subject, is_active=True).first()


def generate_multi_subject_week_plan(profile: StudyProfile, *, replace_pending=False):
    """Build a bounded, deterministic seven-day plan across active subjects."""

    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    if replace_pending:
        profile.tasks.filter(
            status=StudyTask.Status.PENDING,
            scheduled_for__gte=today,
        ).delete()
    elif profile.tasks.filter(
        scheduled_for__gte=today,
        scheduled_for__lt=week_end,
    ).exists():
        return []

    enrollments = list(profile.enrollments.filter(is_active=True).order_by("created_at"))
    if not enrollments:
        return []
    by_subject = {item.subject: item for item in enrollments}
    focus = [item for item in profile.focus_subjects if item in by_subject]
    weighted = focus + focus + [item.subject for item in enrollments if item.subject not in focus]
    if not weighted:
        weighted = list(by_subject)
    selector = cycle(weighted)
    slots_per_day = 1 if profile.daily_minutes < 30 or len(enrollments) == 1 else 2
    duration = max(10, min(30, profile.daily_minutes // slots_per_day))
    created = []
    for offset in range(7):
        day_subjects = []
        attempts = 0
        while len(day_subjects) < min(slots_per_day, len(enrollments)) and attempts < len(weighted) * 3:
            candidate = next(selector)
            attempts += 1
            if candidate not in day_subjects:
                day_subjects.append(candidate)
        for subject in day_subjects:
            enrollment = by_subject[subject]
            label = enrollment.get_subject_display()
            chapter = enrollment.current_chapter or f"{label}基础巩固"
            task, was_created = StudyTask.objects.get_or_create(
                organization=profile.organization,
                profile=profile,
                subject=subject,
                grade_stage=enrollment.grade_stage,
                scheduled_for=today + timedelta(days=offset),
                task_type=StudyTask.Type.SCHOOL_SYNC,
                title=f"同步巩固：{chapter}",
                defaults={"duration_minutes": duration},
            )
            if was_created:
                created.append(task)
    return created


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
        mistake, mistake_created = MistakeRecord.objects.get_or_create(
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
        if mistake_created:
            MistakeCheckIn.objects.get_or_create(
                organization=problem.organization,
                profile=problem.profile,
                subject=problem.subject,
                checked_on=timezone.localdate(),
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


def build_answer_card(
    profile: StudyProfile,
    enrollment: SubjectEnrollment,
    *,
    curriculum_version: str,
    knowledge_point_code: str,
):
    point = get_knowledge_point(
        subject=enrollment.subject,
        curriculum_id=curriculum_version,
        code=knowledge_point_code,
    )
    node = CurriculumNode.objects.filter(
        subject=enrollment.subject,
        grade_stage=enrollment.grade_stage,
        curriculum_version=curriculum_version,
        code=knowledge_point_code,
        node_type=CurriculumNode.NodeType.KNOWLEDGE_POINT,
    ).first()
    if node is None:
        raise ValueError("知识点尚未同步，请先同步教学数据。")
    return AnswerCard.objects.create(
        organization=profile.organization,
        profile=profile,
        subject=enrollment.subject,
        grade_stage=enrollment.grade_stage,
        curriculum_version=curriculum_version,
        knowledge_point=node,
        knowledge_point_code=knowledge_point_code,
        knowledge_point_name=point["name"],
        questions=point["questions"],
    )


@transaction.atomic
def submit_answer_card(card: AnswerCard, answers: list[dict]):
    locked = AnswerCard.objects.select_for_update().get(pk=card.pk)
    if locked.status == AnswerCard.Status.COMPLETED:
        raise ValueError("答题卡已提交，不能重复交卷。")
    question_by_id = {str(item["id"]): item for item in locked.questions}
    if len(answers) != len(question_by_id):
        raise ValueError("请完成答题卡中的全部题目。")
    answer_by_id = {}
    for answer in answers:
        question_id = str(answer.get("question_id") or "")
        selected_option_id = str(answer.get("selected_option_id") or "")
        if question_id in answer_by_id:
            raise ValueError("同一道题不能重复提交。")
        question = question_by_id.get(question_id)
        if question is None:
            raise ValueError("答案中包含未知题目。")
        option_ids = {str(option["id"]) for option in question["options"]}
        if selected_option_id not in option_ids:
            raise ValueError("所选选项不存在。")
        answer_by_id[question_id] = selected_option_id
    if set(answer_by_id) != set(question_by_id):
        raise ValueError("请完成答题卡中的全部题目。")

    details = []
    correct = 0
    for question_id, question in question_by_id.items():
        selected = answer_by_id[question_id]
        is_correct = selected == question["correct_option_id"]
        correct += int(is_correct)
        details.append({
            "question_id": question_id,
            "selected_option_id": selected,
            "correct_option_id": question["correct_option_id"],
            "is_correct": is_correct,
            "explanation": question["explanation"],
        })
    locked.results = {
        "answers": details,
        "correct": correct,
        "total": len(question_by_id),
    }
    locked.score = round(100 * correct / len(question_by_id)) if question_by_id else 0
    locked.status = AnswerCard.Status.COMPLETED
    locked.completed_at = timezone.now()
    locked.save(update_fields=(
        "results", "score", "status", "completed_at", "updated_at",
    ))

    if locked.knowledge_point_id:
        mastery, _ = KnowledgeMastery.objects.get_or_create(
            organization=locked.organization,
            profile=locked.profile,
            knowledge_point=locked.knowledge_point,
            defaults={
                "subject": locked.subject,
                "grade_stage": locked.grade_stage,
            },
        )
        mastery.attempts_count += len(question_by_id)
        mastery.correct_count += correct
        mastery.score = round(100 * mastery.correct_count / mastery.attempts_count)
        mastery.save(update_fields=(
            "attempts_count", "correct_count", "score", "updated_at",
        ))
    return locked


def start_tutor_run(
    *, problem: Problem, actor, operation: str, student_thought="", hint_level=1,
    agent_id=None,
):
    tutor_definition = TUTOR_DEFINITION_BY_SUBJECT.get(problem.subject)
    tutor_slug = tutor_definition.slug if tutor_definition else TUTOR_AGENT_SLUG
    agent_query = Agent.objects.filter(
        organization=problem.organization,
        is_active=True,
    )
    agent = agent_query.filter(pk=agent_id).first() if agent_id else (
        agent_query.filter(slug=tutor_slug).first()
        or agent_query.filter(slug=TUTOR_AGENT_SLUG).first()
    )
    if agent and agent_id and agent.slug != tutor_slug:
        return None
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
            f"请分析这道{problem.get_subject_display()}题：\n{prompt}"
            if prompt else f"请查看并辅导我上传的这道{problem.get_subject_display()}题，先引导我思考。"
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
            title_source = " ".join(prompt.split())[:48] if prompt else f"{problem.get_subject_display()}图片题目"
            conversation = Conversation.objects.create(
                user=actor,
                organization=problem.organization,
                title=f"{problem.get_subject_display()} · {title_source}",
                agent=agent,
                process_id=f"study-tutor:{problem.id}",
                agent_locked=True,
            )
            locked_problem.conversation = conversation

        history = list(
            conversation.messages.order_by("created_at", "id").values("role", "content")
        )[-99:]
        history.append({"role": "user", "content": message})
        user_message = Message.objects.create(
            conversation=conversation,
            role="user",
            content=visible_message,
            metadata={
                "study_with_method": {
                    "problem_id": str(problem.id),
                    "operation": operation,
                    "hint_level": hint_level,
                },
            },
        )
        runtime_attachments = []
        if locked_problem.source_image and locked_problem.source_attachment_id is None:
            attachment, runtime_attachment = attach_existing_image(
                message=user_message,
                conversation=conversation,
                image_field=locked_problem.source_image,
            )
            locked_problem.source_attachment = attachment
            runtime_attachments.append(runtime_attachment)
        run, replayed = start_agent_run(
            organization_id=problem.organization_id,
            agent_id=agent.id,
            actor=actor,
            input_data={
                "message": message,
                "messages": history,
                "attachments": runtime_attachments,
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
            user_message.metadata = {
                **user_message.metadata,
                "run_id": str(run.id),
            }
            user_message.save(update_fields=("metadata",))
            conversation.save(update_fields=("updated_at",))
        locked_problem.latest_run_id = run.id
        locked_problem.save(update_fields=(
            "conversation", "source_attachment", "latest_run_id", "updated_at",
        ))
        problem.conversation_id = conversation.id
        problem.latest_run_id = run.id
    return run


def resolve_curriculum_node(subject: str, code: str | None, grade_stage: str | None = None):
    if not code:
        return None
    nodes = CurriculumNode.objects.filter(subject=subject, code=code)
    if grade_stage:
        nodes = nodes.filter(grade_stage=grade_stage)
    return nodes.first()

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
    DiagnosticAssessment,
    DiagnosticResult,
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
from .teaching_data import TeachingDataError, get_knowledge_point


REVIEW_INTERVALS = (1, 3, 7, 14)
REVIEW_RATINGS = ("again", "hard", "good")
TUTOR_AGENT_SLUG = "study-with-method-tutor"


def monday_for(value):
    return value - timedelta(days=value.weekday())


def active_enrollment(profile: StudyProfile, subject=Subject.MATH):
    return profile.enrollments.filter(subject=subject, is_active=True).first()


def generate_multi_subject_week_plan(profile: StudyProfile, *, replace_pending=False):
    """Build a bounded adaptive seven-day plan without rewriting completed work."""

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
    weak_subjects = list(
        profile.masteries.filter(score__lt=60)
        .order_by("score")
        .values_list("subject", flat=True)
        .distinct()
    )
    due_subjects = list(
        profile.review_schedules.filter(next_review_at__lte=timezone.now())
        .values_list("subject", flat=True)
        .distinct()
    )
    weighted = (
        due_subjects + weak_subjects + focus + focus
        + [item.subject for item in enrollments if item.subject not in focus]
    )
    days_to_exam = (
        (profile.exam_date - today).days if profile.exam_date and profile.exam_date >= today
        else None
    )
    if days_to_exam is not None and days_to_exam <= 30:
        weighted = focus + focus + weighted
    weighted = [item for item in weighted if item in by_subject]
    if not weighted:
        weighted = list(by_subject)
    selector = cycle(weighted)
    recent_start = today - timedelta(days=7)
    recent = profile.tasks.filter(scheduled_for__gte=recent_start, scheduled_for__lt=today)
    recent_total = recent.count()
    completion_rate = (
        recent.filter(status=StudyTask.Status.COMPLETED).count() / recent_total
        if recent_total else 1
    )
    daily_budget = min(
        profile.daily_minutes,
        max(15, round((profile.weekly_minutes or profile.daily_minutes * 7) / 7)),
    )
    slots_per_day = 1 if daily_budget < 30 or len(enrollments) == 1 else 2
    if completion_rate < 0.5:
        slots_per_day = 1
    duration = max(10, min(30, daily_budget // slots_per_day))
    created = []
    for offset in range(7):
        if offset == 6:
            subject = focus[0] if focus else enrollments[0].subject
            enrollment = by_subject[subject]
            task, was_created = StudyTask.objects.get_or_create(
                organization=profile.organization,
                profile=profile,
                subject=subject,
                grade_stage=enrollment.grade_stage,
                scheduled_for=today + timedelta(days=offset),
                task_type=StudyTask.Type.WEEKLY_QUIZ,
                title=f"{enrollment.get_subject_display()}本周小测与复盘",
                defaults={
                    "duration_minutes": min(20, duration),
                    "metadata": {
                        "priority": "must_do",
                        "recommendation_reason": "用周测校准下周学习计划",
                        "adaptive": True,
                    },
                },
            )
            if was_created:
                created.append(task)
            continue
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
            due_count = profile.review_schedules.filter(
                subject=subject, next_review_at__date__lte=today + timedelta(days=offset)
            ).count()
            weak_topic = (enrollment.weak_topics or [None])[offset % max(1, len(enrollment.weak_topics or []))]
            if due_count:
                task_type = StudyTask.Type.REVIEW
                title = f"到期复习：{label}{due_count} 项"
                reason = f"{due_count} 项复习已到期，优先阻止遗忘"
                priority = "must_do"
            elif weak_topic:
                task_type = StudyTask.Type.WEAK_POINT
                title = f"薄弱点训练：{weak_topic}"
                reason = f"{weak_topic}是当前标记的薄弱点"
                priority = "must_do" if subject in focus else "optional"
            else:
                task_type = StudyTask.Type.SCHOOL_SYNC
                title = f"同步巩固：{chapter}"
                reason = "跟进当前教材进度"
                priority = "must_do" if subject in focus else "optional"
            task, was_created = StudyTask.objects.get_or_create(
                organization=profile.organization,
                profile=profile,
                subject=subject,
                grade_stage=enrollment.grade_stage,
                scheduled_for=today + timedelta(days=offset),
                task_type=task_type,
                title=title,
                defaults={
                    "duration_minutes": duration,
                    "metadata": {
                        "priority": priority,
                        "recommendation_reason": reason,
                        "adaptive": True,
                    },
                },
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
    for index, task in enumerate(overdue):
        task.metadata = {**task.metadata, "rescheduled_from": str(task.scheduled_for)}
        task.scheduled_for = today + timedelta(days=min(index // 2, 2))
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
    if problem.knowledge_point_id and is_correct is not None:
        record_mastery_evidence(
            profile=problem.profile,
            knowledge_point=problem.knowledge_point,
            subject=problem.subject,
            grade_stage=problem.grade_stage,
            is_correct=is_correct,
            hint_level=problem.max_hint_level,
            duration_seconds=duration_seconds,
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


def record_mastery_evidence(
    *, profile: StudyProfile, knowledge_point: CurriculumNode, subject: str,
    grade_stage: str, is_correct: bool, hint_level=0, duration_seconds=0,
):
    """Update mastery from one normalized piece of learning evidence."""

    mastery, _ = KnowledgeMastery.objects.get_or_create(
        organization=profile.organization,
        profile=profile,
        knowledge_point=knowledge_point,
        defaults={"subject": subject, "grade_stage": grade_stage},
    )
    mastery.attempts_count += 1
    if is_correct:
        mastery.correct_count += 1
    evidence = 100 if is_correct else 0
    evidence -= min(30, int(hint_level or 0) * 8)
    if duration_seconds and duration_seconds > 20 * 60:
        evidence -= 5
    evidence = max(0, evidence)
    if mastery.attempts_count == 1:
        mastery.score = evidence
    else:
        mastery.score = round(mastery.score * 0.7 + evidence * 0.3)
    mastery.confidence = min(100, 15 + mastery.attempts_count * 17)
    mastery.last_evidence_at = timezone.now()
    mastery.save(update_fields=(
        "attempts_count", "correct_count", "score", "confidence",
        "last_evidence_at", "updated_at",
    ))
    return mastery


def _review_interval_days(schedule: ReviewSchedule, rating: str):
    if rating == "again":
        return 1
    if rating == "hard":
        return max(2, min(14, 2 + schedule.repetition_streak * 2))
    # ``complete_review`` increments the streak before calculating the interval,
    # so the first successful recall must still use the first (3-day) step.
    index = min(max(schedule.repetition_streak - 1, 0), 4)
    return (3, 7, 14, 30, 60)[index]


def complete_review(schedule: ReviewSchedule, rating: str, *, record_evidence=True):
    if rating not in REVIEW_RATINGS:
        raise ValueError("复习结果必须是 again、hard 或 good。")
    schedule.completed_reviews += 1
    schedule.last_result = rating
    if rating == "good":
        schedule.repetition_streak += 1
        schedule.interval_step = min(schedule.interval_step + 1, len(REVIEW_INTERVALS) - 1)
        schedule.mistake.mastery = min(100, schedule.mistake.mastery + 20)
        schedule.difficulty = max(1, schedule.difficulty - 1)
    elif rating == "hard":
        schedule.repetition_streak = max(0, schedule.repetition_streak - 1)
        schedule.mistake.mastery = min(100, schedule.mistake.mastery + 5)
        schedule.difficulty = min(10, schedule.difficulty + 1)
    else:
        schedule.repetition_streak = 0
        schedule.lapse_count += 1
        schedule.interval_step = 0
        schedule.mistake.mastery = max(0, schedule.mistake.mastery - 15)
        schedule.difficulty = min(10, schedule.difficulty + 2)
    schedule.last_reviewed_at = timezone.now()
    schedule.next_review_at = schedule.last_reviewed_at + timedelta(
        days=_review_interval_days(schedule, rating)
    )
    schedule.mistake.save(update_fields=("mastery", "updated_at"))
    if record_evidence and schedule.mistake.knowledge_point_id:
        record_mastery_evidence(
            profile=schedule.profile,
            knowledge_point=schedule.mistake.knowledge_point,
            subject=schedule.subject,
            grade_stage=schedule.grade_stage,
            is_correct=rating == "good",
            hint_level=1 if rating == "hard" else 0,
        )
    schedule.save(
        update_fields=(
            "completed_reviews",
            "last_result",
            "interval_step",
            "repetition_streak",
            "lapse_count",
            "difficulty",
            "last_reviewed_at",
            "next_review_at",
            "updated_at",
        )
    )
    return schedule


DIAGNOSTIC_CURRICULA = {
    Subject.MATH: "xj-math-current",
    Subject.HISTORY: "pep-history-current",
}


def create_diagnostic_assessment(profile: StudyProfile, subjects=None, *, skip=False):
    selected = [
        value for value in (subjects or profile.focus_subjects or [profile.primary_subject])
        if profile.enrollments.filter(subject=value, is_active=True).exists()
    ]
    selected = list(dict.fromkeys(selected))[:3]
    if not selected:
        raise ValueError("请至少选择一门已启用学科。")
    questions = []
    for subject in selected:
        curriculum_id = DIAGNOSTIC_CURRICULA.get(subject)
        nodes = CurriculumNode.objects.filter(
            subject=subject,
            node_type=CurriculumNode.NodeType.KNOWLEDGE_POINT,
            **({"curriculum_version": curriculum_id} if curriculum_id else {}),
        ).order_by("order")[:2]
        added = 0
        if curriculum_id:
            for node in nodes:
                try:
                    point = get_knowledge_point(
                        subject=subject, curriculum_id=curriculum_id, code=node.code
                    )
                except (KeyError, ValueError, TeachingDataError):
                    continue
                for item in list(point.get("questions") or [])[:2]:
                    questions.append({
                        "id": str(item["id"]),
                        "subject": subject,
                        "knowledge_point_code": node.code,
                        "knowledge_point_name": node.name,
                        "question_type": "objective",
                        "stem": item["stem"],
                        "options": item["options"],
                        "correct_option_id": item["correct_option_id"],
                        "explanation": item.get("explanation", ""),
                    })
                    added += 1
        if not added:
            enrollment = active_enrollment(profile, subject)
            topic = enrollment.current_chapter if enrollment else "当前课程"
            questions.append({
                "id": f"self-{subject}",
                "subject": subject,
                "knowledge_point_code": "",
                "knowledge_point_name": topic or "当前课程",
                "question_type": "self_rating",
                "stem": f"你对{topic or '当前课程'}的掌握程度如何？",
                "options": [],
            })
    assessment = DiagnosticAssessment.objects.create(
        organization=profile.organization,
        profile=profile,
        subjects=selected,
        questions=questions,
        status=(
            DiagnosticAssessment.Status.SKIPPED
            if skip else DiagnosticAssessment.Status.IN_PROGRESS
        ),
        completed_at=timezone.now() if skip else None,
    )
    if skip:
        generate_multi_subject_week_plan(profile, replace_pending=True)
    return assessment


@transaction.atomic
def submit_diagnostic_assessment(assessment: DiagnosticAssessment, answers: list[dict]):
    locked = DiagnosticAssessment.objects.select_for_update().get(pk=assessment.pk)
    if locked.status != DiagnosticAssessment.Status.IN_PROGRESS:
        raise ValueError("这次诊断已经结束。")
    question_by_id = {str(item["id"]): item for item in locked.questions}
    answer_by_id = {str(item.get("question_id") or ""): item for item in answers}
    if set(answer_by_id) != set(question_by_id):
        raise ValueError("请完成诊断中的全部题目。")
    grouped = {}
    for question_id, question in question_by_id.items():
        answer = answer_by_id[question_id]
        if question["question_type"] == "objective":
            selected = str(answer.get("selected_option_id") or "")
            option_ids = {str(item["id"]) for item in question["options"]}
            if selected not in option_ids:
                raise ValueError("诊断题包含无效选项。")
            correct = selected == str(question["correct_option_id"])
            response = {"question_id": question_id, "selected_option_id": selected, "is_correct": correct}
            value = 100 if correct else 0
        else:
            rating = int(answer.get("self_rating") or 0)
            if rating < 1 or rating > 5:
                raise ValueError("自评掌握度必须在 1 到 5 之间。")
            response = {"question_id": question_id, "self_rating": rating}
            value = rating * 20
        key = (
            question["subject"], question.get("knowledge_point_code", ""),
            question.get("knowledge_point_name", ""),
        )
        grouped.setdefault(key, []).append((value, response))

    weak_by_subject = {}
    for (subject, code, name), values in grouped.items():
        score = round(sum(item[0] for item in values) / len(values))
        node = CurriculumNode.objects.filter(
            subject=subject, code=code,
            grade_stage=locked.profile.grade_stage,
        ).first() if code else None
        DiagnosticResult.objects.update_or_create(
            organization=locked.organization,
            assessment=locked,
            profile=locked.profile,
            subject=subject,
            knowledge_point_code=code,
            defaults={
                "knowledge_point": node,
                "knowledge_point_name": name,
                "score": score,
                "confidence": min(100, 30 + len(values) * 20),
                "responses": [item[1] for item in values],
            },
        )
        if node:
            mastery, _ = KnowledgeMastery.objects.get_or_create(
                organization=locked.organization,
                profile=locked.profile,
                knowledge_point=node,
                defaults={"subject": subject, "grade_stage": locked.profile.grade_stage},
            )
            mastery.score = score
            mastery.confidence = min(100, 30 + len(values) * 20)
            mastery.attempts_count = max(mastery.attempts_count, len(values))
            mastery.correct_count = max(
                mastery.correct_count,
                sum(bool(item[1].get("is_correct")) for item in values),
            )
            mastery.last_evidence_at = timezone.now()
            mastery.save(update_fields=(
                "score", "confidence", "attempts_count", "correct_count",
                "last_evidence_at", "updated_at",
            ))
        if score < 60:
            weak_by_subject.setdefault(subject, []).append(name)
    for subject, topics in weak_by_subject.items():
        enrollment = active_enrollment(locked.profile, subject)
        if enrollment:
            enrollment.weak_topics = list(dict.fromkeys([
                *(enrollment.weak_topics or []), *[item for item in topics if item],
            ]))
            enrollment.save(update_fields=("weak_topics", "updated_at"))
    locked.status = DiagnosticAssessment.Status.COMPLETED
    locked.completed_at = timezone.now()
    locked.save(update_fields=("status", "completed_at", "updated_at"))
    generate_multi_subject_week_plan(locked.profile, replace_pending=True)
    return locked


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
    if metrics["due_review_count"]:
        advice = f"下周先清理 {metrics['due_review_count']} 项到期复习，再推进“{enrollment.current_chapter or '当前章节'}”。"
    elif metrics["correct_rate"] and metrics["correct_rate"] < 60:
        advice = "下周减少新题数量，优先重做近期错题并用三档反馈校准复习间隔。"
    elif metrics["completion_rate"] < 60:
        advice = "下周保持重点科不变，但缩短单次任务，先恢复稳定完成节奏。"
    else:
        advice = f"当前节奏稳定，下周继续跟进“{enrollment.current_chapter or '当前章节'}”并完成周测。"
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
            "next_week_advice": advice,
        },
    )
    return report


def build_weekly_quiz(profile: StudyProfile, enrollment: SubjectEnrollment):
    mistakes = list(
        profile.mistakes.filter(subject=enrollment.subject, is_archived=False)
        .select_related("problem", "knowledge_point")
        .order_by("mastery", "-updated_at")[:5]
    )
    if not mistakes:
        raise ValueError("至少记录一道错题后才能生成周测。")
    questions = []
    for mistake in mistakes:
        problem = mistake.problem
        options = list((problem.analysis or {}).get("options") or [])
        correct_option_id = str((problem.answer_key or {}).get("answer") or "")
        is_objective = bool(correct_option_id and options)
        questions.append({
            "id": str(uuid.uuid4()),
            "prompt": problem.confirmed_text or problem.original_text,
            "knowledge_point": (
                mistake.knowledge_point.code if mistake.knowledge_point else ""
            ),
            "source_problem_id": str(problem.id),
            "question_type": "objective" if is_objective else "self_review",
            "options": options if is_objective else [],
            "correct_option_id": correct_option_id if is_objective else "",
            "reference_answer": mistake.correct_answer,
            "validation_status": (
                "server_verified" if is_objective else "self_assessment"
            ),
        })
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


@transaction.atomic
def submit_weekly_quiz(quiz: WeeklyQuiz, answers: list[dict]):
    locked = WeeklyQuiz.objects.select_for_update().get(pk=quiz.pk)
    if locked.status == WeeklyQuiz.Status.COMPLETED:
        raise ValueError("周测已提交，不能重复交卷。")
    question_by_id = {str(question["id"]): question for question in locked.questions}
    known = set(question_by_id)
    if len(answers) != len(known):
        raise ValueError("请完成周测中的全部题目。")
    answer_by_id = {}
    for answer in answers:
        question_id = str(answer.get("question_id") or "")
        if question_id in answer_by_id:
            raise ValueError("同一道周测题不能重复提交。")
        if question_id not in known:
            raise ValueError("答案中包含未知周测题。")
        answer_by_id[question_id] = answer
    if set(answer_by_id) != known:
        raise ValueError("请完成周测中的全部题目。")
    details = []
    correct = 0
    for question_id, question in question_by_id.items():
        answer = answer_by_id[question_id]
        if question.get("question_type") == "objective":
            selected = str(answer.get("selected_option_id") or "")
            option_ids = {str(item.get("id") or "") for item in question.get("options", [])}
            if selected not in option_ids:
                raise ValueError("周测客观题必须提交有效选项。")
            is_correct = selected == str(question.get("correct_option_id") or "")
            rating = "good" if is_correct else "again"
            detail = {
                "question_id": question_id,
                "selected_option_id": selected,
                "correct_option_id": str(question.get("correct_option_id") or ""),
                "is_correct": is_correct,
            }
        else:
            rating = str(answer.get("rating") or "")
            if rating not in REVIEW_RATINGS:
                raise ValueError("主观题必须选择不会、模糊或会了。")
            is_correct = rating == "good"
            detail = {
                "question_id": question_id,
                "rating": rating,
                "is_correct": is_correct,
                "reference_answer": question.get("reference_answer", ""),
            }
        correct += int(is_correct)
        problem = Problem.objects.filter(
            profile=locked.profile, pk=question.get("source_problem_id")
        ).first()
        if problem:
            record_attempt(
                problem=problem,
                response=detail.get("selected_option_id", rating),
                thought="周测复盘",
                duration_seconds=0,
                is_correct=is_correct,
            )
            schedule = ReviewSchedule.objects.filter(
                profile=locked.profile, mistake__problem=problem
            ).first()
            if schedule:
                complete_review(schedule, rating, record_evidence=False)
        details.append(detail)
    locked.results = {
        "answers": details,
        "correct": correct,
        "total": len(known),
    }
    locked.score = round(100 * correct / len(known)) if known else 0
    locked.status = WeeklyQuiz.Status.COMPLETED
    locked.completed_at = timezone.now()
    locked.save(
        update_fields=("results", "score", "status", "completed_at", "updated_at")
    )
    locked.profile.tasks.filter(
        subject=locked.subject,
        task_type=StudyTask.Type.WEEKLY_QUIZ,
        scheduled_for__gte=locked.week_start,
        scheduled_for__lt=locked.week_start + timedelta(days=7),
    ).update(status=StudyTask.Status.COMPLETED, completed_at=timezone.now())
    generate_multi_subject_week_plan(locked.profile, replace_pending=True)
    enrollment = active_enrollment(locked.profile, locked.subject)
    if enrollment:
        build_weekly_report(locked.profile, enrollment)
    return locked


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


def _upsert_answer_card_problem(card: AnswerCard, question: dict, selected_option_id: str):
    option_by_id = {str(item["id"]): str(item["text"]) for item in question["options"]}
    question_text = "\n".join([
        str(question["stem"]),
        *(f"{item['id']}. {item['text']}" for item in question["options"]),
    ])
    correct_option_id = str(question["correct_option_id"])
    analysis = {
        "answer_card_id": str(card.id),
        "question_id": str(question["id"]),
        "selected_option_id": selected_option_id,
        "selected_option_text": option_by_id[selected_option_id],
        "options": question["options"],
    }
    problem = Problem.objects.filter(
        organization=card.organization,
        profile=card.profile,
        source="answer_card",
        analysis__question_id=str(question["id"]),
    ).first()
    values = {
        "subject": card.subject,
        "grade_stage": card.grade_stage,
        "knowledge_point": card.knowledge_point,
        "original_text": question_text,
        "confirmed_text": question_text,
        "status": Problem.Status.COMPLETED,
        "analysis": analysis,
        "answer_key": {
            "answer": correct_option_id,
            "answer_text": option_by_id[correct_option_id],
            "explanation": question["explanation"],
        },
    }
    if problem is None:
        problem = Problem.objects.create(
            organization=card.organization,
            profile=card.profile,
            source="answer_card",
            **values,
        )
    else:
        for field, value in values.items():
            setattr(problem, field, value)
        problem.save(update_fields=(*values.keys(), "updated_at"))
    return problem


def _upsert_answer_card_mistake(
    card: AnswerCard,
    question: dict,
    selected_option_id: str,
):
    option_by_id = {
        str(option["id"]): str(option["text"])
        for option in question["options"]
    }
    question_text = "\n".join([
        str(question["stem"]),
        *(f"{option['id']}. {option['text']}" for option in question["options"]),
    ])
    correct_option_id = str(question["correct_option_id"])
    correct_answer = (
        f"{correct_option_id}. {option_by_id[correct_option_id]}\n"
        f"解析：{question['explanation']}"
    )
    analysis = {
        "answer_card_id": str(card.id),
        "question_id": str(question["id"]),
        "selected_option_id": selected_option_id,
        "selected_option_text": option_by_id[selected_option_id],
        "options": question["options"],
    }
    problem = Problem.objects.filter(
        organization=card.organization,
        profile=card.profile,
        source="answer_card",
        analysis__question_id=str(question["id"]),
    ).first()
    if problem is None:
        problem = Problem.objects.create(
            organization=card.organization,
            profile=card.profile,
            subject=card.subject,
            grade_stage=card.grade_stage,
            knowledge_point=card.knowledge_point,
            original_text=question_text,
            confirmed_text=question_text,
            source="answer_card",
            status=Problem.Status.COMPLETED,
            analysis=analysis,
            answer_key={
                "answer": correct_option_id,
                "answer_text": option_by_id[correct_option_id],
                "explanation": question["explanation"],
            },
        )
    else:
        problem.subject = card.subject
        problem.grade_stage = card.grade_stage
        problem.knowledge_point = card.knowledge_point
        problem.original_text = question_text
        problem.confirmed_text = question_text
        problem.status = Problem.Status.COMPLETED
        problem.analysis = analysis
        problem.answer_key = {
            "answer": correct_option_id,
            "answer_text": option_by_id[correct_option_id],
            "explanation": question["explanation"],
        }
        problem.save(update_fields=(
            "subject", "grade_stage", "knowledge_point", "original_text",
            "confirmed_text", "status", "analysis", "answer_key", "updated_at",
        ))

    mistake, created = MistakeRecord.objects.get_or_create(
        organization=card.organization,
        profile=card.profile,
        problem=problem,
        defaults={
            "subject": card.subject,
            "grade_stage": card.grade_stage,
            "knowledge_point": card.knowledge_point,
            "cause": MistakeRecord.Cause.CONCEPT,
            "knowledge_summary": card.knowledge_point_name,
            "notes": (
                f"答题卡选择：{selected_option_id}. "
                f"{option_by_id[selected_option_id]}"
            ),
            "correct_answer": correct_answer,
            "similar_problem_types": question.get("tags", []),
        },
    )
    if not created:
        mistake.subject = card.subject
        mistake.grade_stage = card.grade_stage
        mistake.knowledge_point = card.knowledge_point
        mistake.knowledge_summary = card.knowledge_point_name
        mistake.notes = (
            f"答题卡选择：{selected_option_id}. "
            f"{option_by_id[selected_option_id]}"
        )
        mistake.correct_answer = correct_answer
        mistake.similar_problem_types = question.get("tags", [])
        mistake.mastery = max(0, mistake.mastery - 10)
        mistake.save(update_fields=(
            "subject", "grade_stage", "knowledge_point", "knowledge_summary",
            "notes", "correct_answer", "similar_problem_types", "mastery",
            "updated_at",
        ))
    ReviewSchedule.objects.update_or_create(
        organization=card.organization,
        profile=card.profile,
        mistake=mistake,
        defaults={
            "subject": card.subject,
            "grade_stage": card.grade_stage,
            "interval_step": 0,
            "last_result": "incorrect",
            "next_review_at": timezone.now() + timedelta(days=REVIEW_INTERVALS[0]),
        },
    )
    MistakeCheckIn.objects.get_or_create(
        organization=card.organization,
        profile=card.profile,
        subject=card.subject,
        checked_on=timezone.localdate(),
    )
    return mistake


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
        detail = {
            "question_id": question_id,
            "selected_option_id": selected,
            "correct_option_id": question["correct_option_id"],
            "is_correct": is_correct,
            "explanation": question["explanation"],
        }
        if not is_correct:
            mistake = _upsert_answer_card_mistake(locked, question, selected)
            detail["mistake_id"] = str(mistake.id)
            problem = mistake.problem
        else:
            problem = _upsert_answer_card_problem(locked, question, selected)
        record_attempt(
            problem=problem,
            response=selected,
            thought="知识点答题卡",
            duration_seconds=0,
            is_correct=is_correct,
        )
        details.append(detail)
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

    generate_multi_subject_week_plan(locked.profile, replace_pending=True)
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

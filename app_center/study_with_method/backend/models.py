"""Tenant-scoped learning data for 学之有道."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from modules.tenancy.models import TenantOwnedModel


class Subject(models.TextChoices):
    CHINESE = "chinese", "语文"
    MATH = "math", "数学"
    ENGLISH = "english", "英语"
    PHYSICS = "physics", "物理"
    CHEMISTRY = "chemistry", "化学"
    BIOLOGY = "biology", "生物"
    POLITICS = "politics", "思想政治"
    HISTORY = "history", "历史"
    GEOGRAPHY = "geography", "地理"


class GradeStage(models.TextChoices):
    HIGH_1 = "high_1", "高一"
    HIGH_2 = "high_2", "高二"
    HIGH_3 = "high_3", "高三"


def study_problem_upload_path(instance, filename):
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return (
        f"study-with-method/{instance.organization_id}/"
        f"{instance.profile_id}/{instance.id}.{suffix}"
    )


def default_enabled_subjects():
    return list(Subject.values)


class StudyWorkspace(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.OneToOneField(
        "applications.Application",
        on_delete=models.CASCADE,
        related_name="study_workspace",
    )
    enabled_subjects = models.JSONField(default=default_enabled_subjects)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_workspaces"


class StudyProfile(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        StudyWorkspace, on_delete=models.CASCADE, related_name="profiles"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_profiles",
    )
    display_name = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=120, blank=True)
    primary_subject = models.CharField(
        max_length=32, choices=Subject.choices, default=Subject.MATH, db_index=True
    )
    grade_stage = models.CharField(
        max_length=32, choices=GradeStage.choices, default=GradeStage.HIGH_2, db_index=True
    )
    daily_minutes = models.PositiveSmallIntegerField(default=45)
    weekly_minutes = models.PositiveSmallIntegerField(default=315)
    exam_date = models.DateField(null=True, blank=True)
    focus_subjects = models.JSONField(default=list, blank=True)
    last_tutor_subject = models.CharField(
        max_length=32, choices=Subject.choices, blank=True, default=""
    )
    latest_score = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    target_score = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_profiles"
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "student"), name="unique_study_profile_student"
            )
        ]


class StudyGoal(TenantOwnedModel):
    """A concrete, per-subject target used by the adaptive planner."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="goals"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    exam_date = models.DateField(null=True, blank=True)
    target_score = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    weekly_minutes = models.PositiveSmallIntegerField(default=315)
    focus_chapters = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_goals"
        ordering = ("exam_date", "subject")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "subject"), name="unique_study_goal_subject"
            )
        ]


class DiagnosticAssessment(TenantOwnedModel):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "进行中"
        COMPLETED = "completed", "已完成"
        SKIPPED = "skipped", "已跳过"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="diagnostics"
    )
    subjects = models.JSONField(default=list)
    questions = models.JSONField(default=list)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IN_PROGRESS, db_index=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_diagnostic_assessments"
        ordering = ("-created_at",)


class DiagnosticResult(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        DiagnosticAssessment, on_delete=models.CASCADE, related_name="results"
    )
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="diagnostic_results"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    knowledge_point = models.ForeignKey(
        "CurriculumNode", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="diagnostic_results",
    )
    knowledge_point_code = models.CharField(max_length=180, blank=True)
    knowledge_point_name = models.CharField(max_length=160, blank=True)
    score = models.PositiveSmallIntegerField(default=0)
    confidence = models.PositiveSmallIntegerField(default=0)
    responses = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "study_diagnostic_results"
        ordering = ("subject", "score")
        constraints = [
            models.UniqueConstraint(
                fields=("assessment", "subject", "knowledge_point_code"),
                name="unique_study_diagnostic_result",
            )
        ]


class SubjectEnrollment(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="enrollments"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(
        max_length=32, choices=GradeStage.choices, db_index=True
    )
    curriculum_version = models.CharField(max_length=120, blank=True, default="")
    current_chapter = models.CharField(max_length=160, blank=True, default="")
    weak_topics = models.JSONField(default=list, blank=True)
    latest_score = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    target_score = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_subject_enrollments"
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "subject", "grade_stage"),
                name="unique_study_subject_enrollment",
            )
        ]


class CurriculumNode(models.Model):
    class NodeType(models.TextChoices):
        MODULE = "module", "模块"
        VOLUME = "volume", "册次"
        CHAPTER = "chapter", "章节"
        SECTION = "section", "小节"
        KNOWLEDGE_POINT = "knowledge_point", "知识点"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(
        max_length=32, choices=GradeStage.choices, db_index=True
    )
    curriculum_version = models.CharField(max_length=120, db_index=True)
    # Dotted, subject-namespaced identifiers are deliberate (for example
    # ``math.function.monotonicity``); SlugField rejects dots in forms.
    code = models.CharField(max_length=180)
    name = models.CharField(max_length=160)
    node_type = models.CharField(max_length=32, choices=NodeType.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    order = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "study_curriculum_nodes"
        ordering = ("subject", "curriculum_version", "order", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("subject", "grade_stage", "curriculum_version", "code"),
                name="unique_study_curriculum_node",
            )
        ]


class StudyTask(TenantOwnedModel):
    class Type(models.TextChoices):
        SCHOOL_SYNC = "school_sync", "校内同步"
        WEAK_POINT = "weak_point", "薄弱点训练"
        REVIEW = "review", "到期复习"
        WEEKLY_QUIZ = "weekly_quiz", "周测"

    class Status(models.TextChoices):
        PENDING = "pending", "待完成"
        COMPLETED = "completed", "已完成"
        SKIPPED = "skipped", "已跳过"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="tasks"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    knowledge_point = models.ForeignKey(
        CurriculumNode,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    task_type = models.CharField(max_length=32, choices=Type.choices)
    title = models.CharField(max_length=180)
    scheduled_for = models.DateField(db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(default=15)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_tasks"
        ordering = ("scheduled_for", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "subject", "scheduled_for", "task_type", "title"),
                name="unique_study_daily_task",
            )
        ]


class Problem(TenantOwnedModel):
    class Status(models.TextChoices):
        NEEDS_CONFIRMATION = "needs_confirmation", "待确认"
        READY = "ready", "可辅导"
        COMPLETED = "completed", "已完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="problems"
    )
    conversation = models.ForeignKey(
        "conversations.Conversation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="study_problems",
    )
    source_attachment = models.ForeignKey(
        "conversations.MessageAttachment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="study_problems",
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    knowledge_point = models.ForeignKey(
        CurriculumNode,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="problems",
    )
    source_image = models.FileField(
        upload_to=study_problem_upload_path, blank=True, max_length=500
    )
    original_text = models.TextField(blank=True)
    confirmed_text = models.TextField(blank=True)
    source = models.CharField(max_length=32, default="camera")
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.NEEDS_CONFIRMATION
    )
    max_hint_level = models.PositiveSmallIntegerField(default=0)
    analysis = models.JSONField(default=dict, blank=True)
    answer_key = models.JSONField(default=dict, blank=True)
    latest_run_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_problems"
        ordering = ("-created_at",)


class Attempt(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="attempts"
    )
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="attempts"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    response = models.TextField(blank=True)
    student_thought = models.TextField(blank=True)
    is_correct = models.BooleanField(null=True)
    hint_level_used = models.PositiveSmallIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "study_attempts"
        ordering = ("-created_at",)


class MistakeRecord(TenantOwnedModel):
    class Cause(models.TextChoices):
        CONCEPT = "concept", "概念不清"
        FORMULA = "formula", "公式遗忘"
        MEMORY = "memory", "记忆不牢"
        READING = "reading", "审题错误"
        CALCULATION = "calculation", "计算错误"
        METHOD = "method", "方法选择"
        EXPRESSION = "expression", "表达不规范"
        EXPERIMENT = "experiment", "实验分析"
        CARELESS = "careless", "粗心"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="mistakes"
    )
    problem = models.OneToOneField(
        Problem, on_delete=models.CASCADE, related_name="mistake"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    knowledge_point = models.ForeignKey(
        CurriculumNode,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mistakes",
    )
    cause = models.CharField(max_length=32, choices=Cause.choices, default=Cause.CONCEPT)
    knowledge_summary = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    correct_answer = models.TextField(blank=True)
    similar_problem_types = models.JSONField(default=list, blank=True)
    mastery = models.PositiveSmallIntegerField(default=20)
    is_archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_mistakes"
        ordering = ("-updated_at",)


class MistakeCheckIn(TenantOwnedModel):
    """A student's once-per-day commitment to revisit mistakes for one subject."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="mistake_check_ins"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    checked_on = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "study_mistake_check_ins"
        ordering = ("-checked_on", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "subject", "checked_on"),
                name="unique_study_mistake_check_in",
            )
        ]


class ReviewSchedule(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="review_schedules"
    )
    mistake = models.OneToOneField(
        MistakeRecord, on_delete=models.CASCADE, related_name="review_schedule"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    interval_step = models.PositiveSmallIntegerField(default=0)
    next_review_at = models.DateTimeField(db_index=True)
    last_result = models.CharField(max_length=20, blank=True)
    completed_reviews = models.PositiveSmallIntegerField(default=0)
    repetition_streak = models.PositiveSmallIntegerField(default=0)
    lapse_count = models.PositiveSmallIntegerField(default=0)
    difficulty = models.PositiveSmallIntegerField(default=5)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_review_schedules"
        ordering = ("next_review_at",)


class KnowledgeMastery(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="masteries"
    )
    knowledge_point = models.ForeignKey(
        CurriculumNode, on_delete=models.CASCADE, related_name="masteries"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    score = models.PositiveSmallIntegerField(default=0)
    attempts_count = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    confidence = models.PositiveSmallIntegerField(default=0)
    last_evidence_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_knowledge_masteries"
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "knowledge_point"),
                name="unique_study_knowledge_mastery",
            )
        ]


class GuardianLink(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="guardian_links"
    )
    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardian_study_links",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_guardian_study_links",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "study_guardian_links"
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "guardian"), name="unique_study_guardian_link"
            )
        ]


class WeeklyReport(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="weekly_reports"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    week_start = models.DateField(db_index=True)
    metrics = models.JSONField(default=dict)
    summary = models.TextField(blank=True)
    next_week_advice = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_weekly_reports"
        ordering = ("-week_start",)
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "subject", "grade_stage", "week_start"),
                name="unique_study_weekly_report",
            )
        ]


class WeeklyQuiz(TenantOwnedModel):
    class Status(models.TextChoices):
        READY = "ready", "待完成"
        COMPLETED = "completed", "已完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="weekly_quizzes"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    week_start = models.DateField(db_index=True)
    questions = models.JSONField(default=list)
    results = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.READY, db_index=True
    )
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_weekly_quizzes"
        ordering = ("-week_start",)
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "subject", "grade_stage", "week_start"),
                name="unique_study_weekly_quiz",
            )
        ]


class AnswerCard(TenantOwnedModel):
    class Status(models.TextChoices):
        READY = "ready", "待提交"
        COMPLETED = "completed", "已完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudyProfile, on_delete=models.CASCADE, related_name="answer_cards"
    )
    subject = models.CharField(max_length=32, choices=Subject.choices, db_index=True)
    grade_stage = models.CharField(max_length=32, choices=GradeStage.choices)
    curriculum_version = models.CharField(max_length=120, db_index=True)
    knowledge_point = models.ForeignKey(
        CurriculumNode,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="answer_cards",
    )
    knowledge_point_code = models.CharField(max_length=180, db_index=True)
    knowledge_point_name = models.CharField(max_length=160)
    questions = models.JSONField(default=list)
    results = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.READY, db_index=True
    )
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "study_answer_cards"
        ordering = ("-created_at",)

from rest_framework import serializers

from .models import (
    Attempt,
    GradeStage,
    GuardianLink,
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


class EnrollmentSerializer(serializers.ModelSerializer):
    subject_label = serializers.CharField(source="get_subject_display", read_only=True)
    grade_stage_label = serializers.CharField(source="get_grade_stage_display", read_only=True)

    class Meta:
        model = SubjectEnrollment
        fields = (
            "id", "subject", "subject_label", "grade_stage", "grade_stage_label",
            "curriculum_version", "current_chapter", "weak_topics", "is_active",
        )
        read_only_fields = ("id", "subject_label", "grade_stage_label")

    def validate_subject(self, value):
        get_subject_strategy(value)
        if value != Subject.MATH:
            raise serializers.ValidationError("首版只开放数学。")
        return value


class ProfileSerializer(serializers.ModelSerializer):
    enrollment = serializers.SerializerMethodField()
    student_name = serializers.CharField(source="student.username", read_only=True)

    class Meta:
        model = StudyProfile
        fields = (
            "id", "student_name", "display_name", "region", "daily_minutes",
            "primary_subject", "grade_stage", "latest_score", "target_score",
            "onboarding_completed", "enrollment",
            "created_at", "updated_at",
        )

    def get_enrollment(self, obj):
        enrollment = obj.enrollments.filter(is_active=True).first()
        return EnrollmentSerializer(enrollment).data if enrollment else None


class ProfileInputSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    region = serializers.CharField(max_length=120, required=False, allow_blank=True)
    daily_minutes = serializers.IntegerField(min_value=15, max_value=240, default=45)
    latest_score = serializers.DecimalField(
        max_digits=5, decimal_places=1, min_value=0, max_value=150,
        required=False, allow_null=True,
    )
    target_score = serializers.DecimalField(
        max_digits=5, decimal_places=1, min_value=0, max_value=150,
        required=False, allow_null=True,
    )
    subject = serializers.ChoiceField(choices=Subject.choices, default=Subject.MATH)
    grade_stage = serializers.ChoiceField(
        choices=GradeStage.choices, default=GradeStage.HIGH_2
    )
    curriculum_version = serializers.CharField(max_length=120)
    current_chapter = serializers.CharField(max_length=160)
    weak_topics = serializers.ListField(
        child=serializers.CharField(max_length=160), required=False, default=list
    )

    def validate_subject(self, value):
        get_subject_strategy(value)
        return value

    def validate(self, attrs):
        if attrs["subject"] != Subject.MATH or attrs["grade_stage"] != GradeStage.HIGH_2:
            raise serializers.ValidationError("首版只开放高二数学。")
        if (
            attrs.get("latest_score") is not None
            and attrs.get("target_score") is not None
            and attrs["target_score"] < attrs["latest_score"]
        ):
            raise serializers.ValidationError({"target_score": "目标分数不能低于最近成绩。"})
        return attrs


class StudyTaskSerializer(serializers.ModelSerializer):
    task_type_label = serializers.CharField(source="get_task_type_display", read_only=True)
    knowledge_point_name = serializers.CharField(
        source="knowledge_point.name", read_only=True, allow_null=True
    )

    class Meta:
        model = StudyTask
        fields = (
            "id", "subject", "grade_stage", "task_type", "task_type_label", "title",
            "scheduled_for", "duration_minutes", "status", "completed_at",
            "knowledge_point_name", "metadata",
        )


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attempt
        fields = (
            "id", "subject", "grade_stage", "response", "student_thought",
            "is_correct", "hint_level_used", "duration_seconds", "created_at",
        )


class ProblemSerializer(serializers.ModelSerializer):
    source_image_url = serializers.SerializerMethodField()
    knowledge_point_code = serializers.CharField(
        source="knowledge_point.code", read_only=True, allow_null=True
    )
    knowledge_point_name = serializers.CharField(
        source="knowledge_point.name", read_only=True, allow_null=True
    )
    attempts = AttemptSerializer(many=True, read_only=True)

    class Meta:
        model = Problem
        fields = (
            "id", "conversation_id", "subject", "grade_stage", "source_image_url", "original_text",
            "confirmed_text", "source", "status", "max_hint_level", "analysis",
            "knowledge_point_code", "knowledge_point_name", "latest_run_id", "attempts",
            "created_at", "updated_at",
        )

    def get_source_image_url(self, obj):
        if not obj.source_image:
            return ""
        # Keep uploaded images on the browser's current origin. Absolute URLs
        # generated behind the Vite proxy point at localhost:8080, which is not
        # reachable from a phone opening the frontend over the LAN.
        return f"/{obj.source_image.url.lstrip('/')}"


class ProblemInputSerializer(serializers.Serializer):
    subject = serializers.ChoiceField(choices=Subject.choices, default=Subject.MATH)
    grade_stage = serializers.ChoiceField(
        choices=GradeStage.choices, default=GradeStage.HIGH_2
    )
    problem_text = serializers.CharField(required=False, allow_blank=True)
    source_image = serializers.FileField(required=False, allow_null=True)
    source = serializers.ChoiceField(
        choices=("camera", "upload", "manual"), default="camera"
    )

    def validate_subject(self, value):
        get_subject_strategy(value)
        return value

    def validate_source_image(self, value):
        if value is None:
            return value
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("题目图片不能超过 10 MB。")
        content_type = str(getattr(value, "content_type", ""))
        if content_type and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise serializers.ValidationError("仅支持 JPG、PNG 或 WebP 图片。")
        return value

    def validate(self, attrs):
        if attrs["subject"] != Subject.MATH or attrs["grade_stage"] != GradeStage.HIGH_2:
            raise serializers.ValidationError("首版只开放高二数学。")
        if not attrs.get("problem_text", "").strip() and not attrs.get("source_image"):
            raise serializers.ValidationError("请拍摄题目或手动输入题目内容。")
        return attrs


class ManualMistakeInputSerializer(serializers.Serializer):
    subject = serializers.ChoiceField(choices=Subject.choices, default=Subject.MATH)
    grade_stage = serializers.ChoiceField(
        choices=GradeStage.choices, default=GradeStage.HIGH_2
    )
    problem_text = serializers.CharField(required=False, allow_blank=True)
    source_image = serializers.FileField(required=False, allow_null=True)
    knowledge_summary = serializers.CharField(
        max_length=500, required=False, allow_blank=True
    )
    cause = serializers.ChoiceField(
        choices=MistakeRecord.Cause.choices, default=MistakeRecord.Cause.CONCEPT
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    correct_answer = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    similar_problem_types = serializers.ListField(
        child=serializers.CharField(max_length=300),
        max_length=20,
        required=False,
        default=list,
    )

    def validate_subject(self, value):
        get_subject_strategy(value)
        return value

    def validate_source_image(self, value):
        if value is None:
            return value
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("题目图片不能超过 10 MB。")
        content_type = str(getattr(value, "content_type", ""))
        if content_type and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise serializers.ValidationError("仅支持 JPG、PNG 或 WebP 图片。")
        return value

    def validate_similar_problem_types(self, value):
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    def validate(self, attrs):
        if attrs["subject"] != Subject.MATH or attrs["grade_stage"] != GradeStage.HIGH_2:
            raise serializers.ValidationError("首版只开放高二数学。")
        if not attrs.get("problem_text", "").strip() and not attrs.get("source_image"):
            raise serializers.ValidationError("请上传题目图片或输入题目文字。")
        strategy = get_subject_strategy(attrs["subject"])
        if attrs["cause"] not in strategy.mistake_causes:
            raise serializers.ValidationError({"cause": "该错因不适用于当前学科。"})
        return attrs


class MistakeUpdateSerializer(serializers.Serializer):
    cause = serializers.ChoiceField(choices=MistakeRecord.Cause.choices, required=False)
    knowledge_summary = serializers.CharField(
        max_length=500, required=False, allow_blank=True
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    correct_answer = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    similar_problem_types = serializers.ListField(
        child=serializers.CharField(max_length=300),
        max_length=20,
        required=False,
    )

    def validate_similar_problem_types(self, value):
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class AttemptInputSerializer(serializers.Serializer):
    response = serializers.CharField(required=False, allow_blank=True)
    student_thought = serializers.CharField(required=False, allow_blank=True)
    duration_seconds = serializers.IntegerField(min_value=0, max_value=86400, default=0)
    is_correct = serializers.BooleanField(required=False, allow_null=True)


class MistakeSerializer(serializers.ModelSerializer):
    problem = ProblemSerializer(read_only=True)
    cause_label = serializers.CharField(source="get_cause_display", read_only=True)
    next_review_at = serializers.DateTimeField(
        source="review_schedule.next_review_at", read_only=True, allow_null=True
    )

    class Meta:
        model = MistakeRecord
        fields = (
            "id", "subject", "grade_stage", "problem", "cause", "cause_label",
            "knowledge_summary", "notes", "correct_answer", "similar_problem_types",
            "mastery", "next_review_at", "created_at", "updated_at",
        )


class ReviewSerializer(serializers.ModelSerializer):
    mistake = MistakeSerializer(read_only=True)

    class Meta:
        model = ReviewSchedule
        fields = (
            "id", "subject", "grade_stage", "mistake", "interval_step",
            "next_review_at", "last_result", "completed_reviews", "updated_at",
        )


class MasterySerializer(serializers.ModelSerializer):
    knowledge_point_code = serializers.CharField(source="knowledge_point.code", read_only=True)
    knowledge_point_name = serializers.CharField(source="knowledge_point.name", read_only=True)

    class Meta:
        model = KnowledgeMastery
        fields = (
            "id", "subject", "grade_stage", "knowledge_point_code",
            "knowledge_point_name", "score", "attempts_count", "correct_count", "updated_at",
        )


class GuardianLinkSerializer(serializers.ModelSerializer):
    guardian_name = serializers.CharField(source="guardian.username", read_only=True)
    guardian_email = serializers.CharField(source="guardian.email", read_only=True)

    class Meta:
        model = GuardianLink
        fields = ("id", "guardian_name", "guardian_email", "is_active", "created_at")


class WeeklyReportSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()

    def get_student_name(self, obj):
        return obj.profile.display_name or obj.profile.student.username

    class Meta:
        model = WeeklyReport
        fields = (
            "id", "student_name", "subject", "grade_stage", "week_start", "metrics",
            "summary", "next_week_advice", "created_at", "updated_at",
        )


class WeeklyQuizSerializer(serializers.ModelSerializer):
    question_count = serializers.SerializerMethodField()

    def get_question_count(self, obj):
        return len(obj.questions or [])

    class Meta:
        model = WeeklyQuiz
        fields = (
            "id", "subject", "grade_stage", "week_start", "questions",
            "question_count", "results", "status", "score", "completed_at",
            "created_at", "updated_at",
        )

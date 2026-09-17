from dataclasses import dataclass
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import Application, ApplicationCategory
from apps.conversations.models import Conversation, Message
from apps.enterprise.models import Membership, Organization
from modules.execution.application.projections import project_terminal_run
from modules.execution.models import Run

from ..install import _seed_curriculum
from ..models import (
    GradeStage,
    GuardianLink,
    MistakeRecord,
    Problem,
    ReviewSchedule,
    StudyProfile,
    StudyWorkspace,
    Subject,
    WeeklyReport,
)
from .. import services as study_services
from ..strategies import (
    get_subject_strategy,
    register_subject_strategy,
    unregister_subject_strategy,
)


@pytest.fixture
def study_context(db):
    User = get_user_model()
    student = User.objects.create_user(username="study-student")
    guardian = User.objects.create_user(username="study-guardian", email="parent@example.com")
    outsider = User.objects.create_user(username="study-outsider")
    organization = Organization.objects.create(
        name="Study Family", slug="study-family", owner=student
    )
    Membership.objects.create(
        organization=organization, user=student, role=Membership.Role.VIEWER
    )
    Membership.objects.create(
        organization=organization, user=guardian, role=Membership.Role.VIEWER
    )
    category = ApplicationCategory.objects.create(
        name="Education", slug="study-education"
    )
    application = Application.objects.create(
        organization=organization,
        category=category,
        name="学之有道",
        slug="study-with-method-test",
        description="Study",
        created_by=student,
        kind=Application.Kind.CUSTOM,
    )
    workspace = StudyWorkspace.objects.create(
        organization=organization,
        application=application,
        enabled_subjects=[Subject.MATH],
    )
    _seed_curriculum()
    return {
        "student": student,
        "guardian": guardian,
        "outsider": outsider,
        "organization": organization,
        "application": application,
        "workspace": workspace,
    }


def client(user):
    value = APIClient()
    value.force_authenticate(user)
    return value


def root(context):
    return (
        f"/api/v1/organizations/{context['organization'].id}/applications/"
        f"{context['application'].id}/study"
    )


def create_profile(context):
    return client(context["student"]).put(
        f"{root(context)}/profile",
        {
            "display_name": "小宇",
            "region": "上海",
            "daily_minutes": 45,
            "latest_score": 92,
            "target_score": 110,
            "subject": "math",
            "grade_stage": "high_2",
            "curriculum_version": "人教A版（2019）",
            "current_chapter": "圆锥曲线",
            "weak_topics": ["椭圆", "双曲线"],
        },
        format="json",
    )


@pytest.mark.django_db
def test_onboarding_generates_math_plan_for_viewer(study_context):
    response = create_profile(study_context)

    assert response.status_code == 200, response.data
    assert response.data["enrollment"]["subject"] == "math"
    profile = StudyProfile.objects.get(student=study_context["student"])
    assert profile.tasks.count() == 15
    dashboard = client(study_context["student"]).get(f"{root(study_context)}/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.data["mode"] == "student"
    assert len(dashboard.data["tasks"]) == 2


@pytest.mark.django_db
def test_unavailable_subject_is_rejected(study_context):
    response = client(study_context["student"]).put(
        f"{root(study_context)}/profile",
        {
            "daily_minutes": 45,
            "subject": "physics",
            "grade_stage": "high_2",
            "curriculum_version": "通用版",
            "current_chapter": "运动",
        },
        format="json",
    )
    assert response.status_code == 400
    assert not StudyProfile.objects.exists()


@pytest.mark.django_db
def test_problem_hint_mistake_and_review_flow(study_context):
    assert create_profile(study_context).status_code == 200
    student = client(study_context["student"])
    problem = student.post(
        f"{root(study_context)}/problems",
        {
            "subject": "math",
            "grade_stage": "high_2",
            "problem_text": "已知椭圆的长轴和焦距，求离心率。",
            "source": "manual",
        },
        format="json",
    )
    assert problem.status_code == 201, problem.data
    assert problem.data["knowledge_point_code"] == "math.geometry.analytic"

    hint = student.post(
        f"{root(study_context)}/problems/{problem.data['id']}/hint",
        {"student_thought": "我想先找 a 和 c"},
        format="json",
    )
    assert hint.status_code == 200
    assert hint.data["hint_level"] == 1
    assert hint.data["solution_revealed"] is False

    attempt = student.post(
        f"{root(study_context)}/problems/{problem.data['id']}/attempts",
        {"response": "不会", "student_thought": "", "is_correct": False},
        format="json",
    )
    assert attempt.status_code == 201
    mistake = MistakeRecord.objects.get(problem_id=problem.data["id"])
    review = ReviewSchedule.objects.get(mistake=mistake)
    assert review.next_review_at > timezone.now()
    assert student.get(f"{root(study_context)}/reviews").data == []

    review.next_review_at = timezone.now()
    review.save(update_fields=("next_review_at",))
    completed = student.post(
        f"{root(study_context)}/reviews/{review.id}/complete",
        {"is_correct": True},
        format="json",
    )
    assert completed.status_code == 200
    assert completed.data["interval_step"] == 1

    quiz = student.post(
        f"{root(study_context)}/quizzes", {"subject": "math"}, format="json"
    )
    assert quiz.status_code == 201, quiz.data
    assert quiz.data["question_count"] == 1
    submitted = student.post(
        f"{root(study_context)}/quizzes/{quiz.data['id']}/submit",
        {
            "answers": [{
                "question_id": quiz.data["questions"][0]["id"],
                "is_correct": True,
            }]
        },
        format="json",
    )
    assert submitted.status_code == 200
    assert submitted.data["score"] == 100


@pytest.mark.django_db
def test_manual_mistake_import_accepts_text_image_and_learning_details(study_context):
    assert create_profile(study_context).status_code == 200
    student = client(study_context["student"])

    text_response = student.post(
        f"{root(study_context)}/mistakes",
        {
            "problem_text": "求函数 f(x)=x²-2x 的单调区间。",
            "knowledge_summary": "函数单调性",
            "cause": "method",
            "notes": "没有先求导数并判断符号。",
            "correct_answer": "(-∞,1)递减，(1,+∞)递增。",
            "similar_problem_types": ["含参数函数的单调性", "根据单调性求参数范围"],
        },
        format="multipart",
    )

    assert text_response.status_code == 201, text_response.data
    assert text_response.data["knowledge_summary"] == "函数单调性"
    assert text_response.data["cause"] == "method"
    assert text_response.data["notes"] == "没有先求导数并判断符号。"
    assert text_response.data["correct_answer"].startswith("(-∞,1)")
    assert text_response.data["similar_problem_types"] == [
        "含参数函数的单调性", "根据单调性求参数范围",
    ]
    text_mistake = MistakeRecord.objects.get(pk=text_response.data["id"])
    assert text_mistake.problem.source == "manual_import"
    assert text_mistake.problem.attempts.get().is_correct is False
    assert ReviewSchedule.objects.filter(mistake=text_mistake).exists()

    image = SimpleUploadedFile(
        "question.png",
        b"not-decoded-by-the-api",
        content_type="image/png",
    )
    image_response = student.post(
        f"{root(study_context)}/mistakes",
        {
            "source_image": image,
            "knowledge_summary": "椭圆的离心率",
            "cause": "formula",
            "notes": "记错离心率公式。",
            "correct_answer": "e=c/a",
            "similar_problem_types": ["由焦距和长轴求离心率"],
        },
        format="multipart",
    )

    assert image_response.status_code == 201, image_response.data
    image_mistake = MistakeRecord.objects.get(pk=image_response.data["id"])
    try:
        assert image_mistake.problem.source_image.name.endswith(".png")
        assert image_mistake.problem.confirmed_text == ""
        assert image_response.data["problem"]["source_image_url"].startswith(
            "/media/study-with-method/"
        )
    finally:
        image_mistake.problem.source_image.delete(save=False)


@pytest.mark.django_db
def test_tutor_runs_are_recorded_in_one_problem_conversation(study_context):
    assert create_profile(study_context).status_code == 200
    profile = StudyProfile.objects.get(student=study_context["student"])
    category, _ = AgentCategory.objects.get_or_create(
        slug="study-conversation-test",
        defaults={"name": "Study Conversation Test"},
    )
    agent = Agent.objects.create(
        organization=study_context["organization"],
        category=category,
        name="学之有道辅导老师",
        slug=study_services.TUTOR_AGENT_SLUG,
        description="test",
        created_by=study_context["student"],
        is_public=False,
    )
    problem = Problem.objects.create(
        organization=study_context["organization"],
        profile=profile,
        subject=Subject.MATH,
        grade_stage=GradeStage.HIGH_2,
        original_text="求函数 f(x)=x² 的单调区间。",
        confirmed_text="求函数 f(x)=x² 的单调区间。",
        status=Problem.Status.READY,
    )
    created_runs = []

    def create_completed_run(**kwargs):
        run = Run.objects.create(
            organization=study_context["organization"],
            owner=study_context["student"],
            executor_kind=Run.ExecutorKind.AGENT,
            executor_key="agent-completion",
            source_type=kwargs["source_type"],
            source_id=kwargs["source_id"],
            status=Run.Status.SUCCEEDED,
            input=kwargs["input_data"],
            output_summary={"result": f"辅导结果 {len(created_runs) + 1}"},
        )
        created_runs.append(run)
        return run, False

    with patch.object(
        study_services,
        "start_agent_run",
        side_effect=create_completed_run,
    ) as start_run:
        study_services.start_tutor_run(
            problem=problem,
            actor=study_context["student"],
            operation="analyze",
        )
        project_terminal_run(created_runs[0].id, created_runs[0].output_summary)
        study_services.start_tutor_run(
            problem=problem,
            actor=study_context["student"],
            operation="hint",
            student_thought="我想先看图像。",
            hint_level=2,
        )
        project_terminal_run(created_runs[1].id, created_runs[1].output_summary)

    problem.refresh_from_db()
    conversation = Conversation.objects.get(pk=problem.conversation_id)
    assert conversation.user == study_context["student"]
    assert conversation.organization == study_context["organization"]
    assert conversation.agent == agent
    assert conversation.title.startswith("学之有道 ·")
    assert conversation.process_id == f"study-problem:{problem.id}"
    assert problem.latest_run_id == created_runs[1].id
    assert list(Message.objects.filter(conversation=conversation).values_list(
        "role", "content",
    )) == [
        ("user", "请识别并分析这道数学题：\n求函数 f(x)=x² 的单调区间。"),
        ("assistant", "辅导结果 1"),
        ("user", "我的思路：我想先看图像。\n请给我第 2 级提示。"),
        ("assistant", "辅导结果 2"),
    ]
    assert start_run.call_count == 2
    for call in start_run.call_args_list:
        assert call.kwargs["source_type"] == "conversation"
        assert call.kwargs["source_id"] == str(conversation.id)


@pytest.mark.django_db
def test_guardian_can_only_read_reports(study_context):
    assert create_profile(study_context).status_code == 200
    profile = StudyProfile.objects.get(student=study_context["student"])
    GuardianLink.objects.create(
        organization=study_context["organization"],
        profile=profile,
        guardian=study_context["guardian"],
        created_by=study_context["student"],
    )
    WeeklyReport.objects.create(
        organization=study_context["organization"],
        profile=profile,
        subject=Subject.MATH,
        grade_stage=GradeStage.HIGH_2,
        week_start=timezone.localdate(),
        metrics={"completion_rate": 80},
        summary="本周按计划学习。",
        next_week_advice="继续复习。",
    )
    guardian = client(study_context["guardian"])
    dashboard = guardian.get(f"{root(study_context)}/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.data["mode"] == "guardian"
    assert dashboard.data["reports"][0]["summary"] == "本周按计划学习。"
    assert "problem" not in dashboard.data["reports"][0]
    assert guardian.get(f"{root(study_context)}/mistakes").status_code == 404
    assert guardian.get(f"{root(study_context)}/problems").status_code == 404
    assert client(study_context["outsider"]).get(
        f"{root(study_context)}/dashboard"
    ).status_code == 403


@pytest.mark.django_db
def test_guardian_email_lookup_excludes_student_with_same_email(study_context):
    assert create_profile(study_context).status_code == 200
    shared_email = study_context["guardian"].email
    study_context["student"].email = shared_email
    study_context["student"].save(update_fields=("email",))

    response = client(study_context["student"]).post(
        f"{root(study_context)}/guardians",
        {"identifier": shared_email},
        format="json",
    )

    assert response.status_code == 201, response.data
    link = GuardianLink.objects.get(profile__student=study_context["student"])
    assert link.guardian == study_context["guardian"]


@dataclass(frozen=True)
class DemoSubjectStrategy:
    subject: str = "test-subject"
    version: int = 1

    def detect_topic(self, problem):
        return "test.topic"

    def hint(self, problem, level, student_thought=""):
        return {"hint": "test"}

    def normalize_answer(self, answer):
        return answer.strip()


def test_subject_strategy_registry_accepts_an_extension_without_common_model_changes():
    register_subject_strategy(DemoSubjectStrategy())
    try:
        assert get_subject_strategy("test-subject").detect_topic("anything") == "test.topic"
    finally:
        unregister_subject_strategy("test-subject")

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.agents.high_school_tutors import TUTOR_DEFINITION_BY_SUBJECT
from apps.applications.models import Application, ApplicationCategory
from apps.conversations.models import Conversation, Message, MessageAttachment
from apps.enterprise.models import Membership, Organization
from modules.catalog.models import AgentDeployment, AgentRevision
from modules.catalog.services import canonical_content_hash
from modules.execution.application.projections import project_terminal_run
from modules.execution.models import Run

from ..install import _seed_curriculum
from ..models import (
    AnswerCard,
    GradeStage,
    GuardianLink,
    MistakeCheckIn,
    MistakeRecord,
    Problem,
    ReviewSchedule,
    StudyProfile,
    StudyTask,
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
        visibility=Application.Visibility.ORGANIZATION,
    )
    workspace = StudyWorkspace.objects.create(
        organization=organization,
        application=application,
        enabled_subjects=list(Subject.values),
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


def create_answer_card(context):
    api = client(context["student"])
    response = api.post(
        f"{root(context)}/answer-cards",
        {
            "subject": "math",
            "curriculum_version": "xj-math-current",
            "knowledge_point_code": "math.xj.required-1.sets-logic",
        },
        format="json",
    )
    return api, response


def deploy_subject_tutor(context, subject=Subject.MATH):
    definition = TUTOR_DEFINITION_BY_SUBJECT[subject]
    category, _ = AgentCategory.objects.get_or_create(
        slug="high-school-education",
        defaults={"name": "高中课程辅导"},
    )
    agent = Agent.objects.create(
        organization=context["organization"],
        category=category,
        name=definition.name,
        slug=definition.slug,
        description=definition.description,
        created_by=context["student"],
        is_public=False,
        visibility=Agent.Visibility.ORGANIZATION,
    )
    content = {
        "system_prompt": definition.system_prompt,
        "model_config": {"adapter": "codex"},
    }
    revision = AgentRevision.objects.create(
        organization=context["organization"],
        agent=agent,
        revision_no=1,
        content=content,
        content_hash=canonical_content_hash(content),
        created_by=context["student"],
    )
    AgentDeployment.objects.create(
        organization=context["organization"],
        agent=agent,
        revision=revision,
        updated_by=context["student"],
    )
    return agent


def image_file(name="question.png", image_format="PNG"):
    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (12, 8), color=(244, 242, 233)).save(data, format=image_format)
    content_type = "image/jpeg" if image_format == "JPEG" else "image/png"
    return SimpleUploadedFile(name, data.getvalue(), content_type=content_type)


@pytest.mark.django_db
def test_onboarding_generates_math_plan_for_viewer(study_context):
    response = create_profile(study_context)

    assert response.status_code == 200, response.data
    assert response.data["enrollment"]["subject"] == "math"
    profile = StudyProfile.objects.get(student=study_context["student"])
    assert profile.tasks.count() == 7
    dashboard = client(study_context["student"]).get(f"{root(study_context)}/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.data["mode"] == "student"
    assert len(dashboard.data["tasks"]) == 1


@pytest.mark.django_db
def test_physics_and_high_one_profile_is_supported(study_context):
    response = client(study_context["student"]).put(
        f"{root(study_context)}/profile",
        {
            "daily_minutes": 45,
            "subject": "physics",
            "grade_stage": "high_1",
            "curriculum_version": "通用版",
            "current_chapter": "运动",
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["grade_stage"] == GradeStage.HIGH_1
    assert response.data["enrollments"][0]["subject"] == Subject.PHYSICS
    assert response.data["enrollments"][0]["current_chapter"] == "运动"


@pytest.mark.django_db
def test_catalog_lists_three_grades_and_nine_subjects(study_context):
    response = client(study_context["student"]).get(f"{root(study_context)}/catalog")

    assert response.status_code == 200, response.data
    assert [item["value"] for item in response.data["grades"]] == list(
        GradeStage.values
    )
    assert [item["value"] for item in response.data["subjects"]] == list(
        Subject.values
    )
    assert all(item["chapters"] for item in response.data["subjects"])
    assert all(item["color"].startswith("#") for item in response.data["subjects"])
    math = next(item for item in response.data["subjects"] if item["value"] == "math")
    history = next(item for item in response.data["subjects"] if item["value"] == "history")
    assert math["curriculum_version_options"] == [
        {"id": "xj-math-current", "label": "湘教版（现行）"}
    ]
    assert history["curriculum_version_options"] == [
        {"id": "pep-history-current", "label": "统编人教版（现行）"}
    ]


@pytest.mark.django_db
def test_curriculum_tree_and_answer_card_server_side_grading(study_context):
    assert create_profile(study_context).status_code == 200
    api = client(study_context["student"])
    tree = api.get(
        f"{root(study_context)}/curriculum",
        {"subject": "math", "curriculum_version": "xj-math-current"},
    )
    assert tree.status_code == 200, tree.data
    assert tree.data["label"] == "湘教版（现行）"
    assert len(tree.data["volumes"]) == 4
    first_point = tree.data["volumes"][0]["chapters"][0]["sections"][0][
        "knowledge_points"
    ][0]
    assert first_point["id"] == "math.xj.required-1.sets-logic"
    assert first_point["summary"]
    assert first_point["objectives"]
    assert first_point["prerequisites"]
    assert first_point["common_mistakes"]
    assert first_point["keywords"]
    assert first_point["competency_tags"]
    assert len(first_point["knowledge_items"]) == 5
    assert first_point["knowledge_items"][0]["name"] == "元素与集合的关系"
    assert first_point["knowledge_items"][0]["formulas"] == ["a\\in A", "a\\notin A"]

    api, created = create_answer_card(study_context)
    assert created.status_code == 201, created.data
    assert len(created.data["questions"]) == 5
    assert created.data["results"] == {}
    assert all("correct_option_id" not in item for item in created.data["questions"])
    assert all("explanation" not in item for item in created.data["questions"])

    stored = AnswerCard.objects.get(pk=created.data["id"])
    answers = [
        {
            "question_id": question["id"],
            "selected_option_id": question["correct_option_id"],
        }
        for question in stored.questions
    ]
    submitted = api.post(
        f"{root(study_context)}/answer-cards/{stored.id}/submit",
        {"answers": answers},
        format="json",
    )
    assert submitted.status_code == 200, submitted.data
    assert submitted.data["score"] == 100
    assert submitted.data["status"] == "completed"
    assert len(submitted.data["results"]["answers"]) == 5
    assert all(item["explanation"] for item in submitted.data["results"]["answers"])


@pytest.mark.django_db
def test_wrong_answer_card_question_is_added_to_mistakes_idempotently(study_context):
    assert create_profile(study_context).status_code == 200
    api, created = create_answer_card(study_context)
    assert created.status_code == 201, created.data
    card = AnswerCard.objects.get(pk=created.data["id"])
    first_question = card.questions[0]
    wrong_option = next(
        item["id"]
        for item in first_question["options"]
        if item["id"] != first_question["correct_option_id"]
    )
    answers = [
        {
            "question_id": question["id"],
            "selected_option_id": (
                wrong_option
                if question["id"] == first_question["id"]
                else question["correct_option_id"]
            ),
        }
        for question in card.questions
    ]

    submitted = api.post(
        f"{root(study_context)}/answer-cards/{card.id}/submit",
        {"answers": answers},
        format="json",
    )

    assert submitted.status_code == 200, submitted.data
    assert submitted.data["score"] == 80
    wrong_result = next(
        item for item in submitted.data["results"]["answers"]
        if not item["is_correct"]
    )
    mistake = MistakeRecord.objects.get(pk=wrong_result["mistake_id"])
    assert mistake.problem.source == "answer_card"
    assert mistake.problem.analysis["question_id"] == first_question["id"]
    assert mistake.problem.answer_key["answer"] == first_question["correct_option_id"]
    assert first_question["explanation"] in mistake.correct_answer
    assert mistake.knowledge_summary == card.knowledge_point_name
    assert ReviewSchedule.objects.filter(mistake=mistake).exists()
    assert MistakeCheckIn.objects.filter(
        profile=card.profile,
        subject=card.subject,
        checked_on=timezone.localdate(),
    ).exists()
    listed = api.get(f"{root(study_context)}/mistakes", {"subject": "math"})
    assert listed.status_code == 200, listed.data
    assert [item["id"] for item in listed.data] == [str(mistake.id)]
    assert listed.data[0]["problem"]["confirmed_text"].startswith(
        first_question["stem"]
    )

    _, second_created = create_answer_card(study_context)
    second_card = AnswerCard.objects.get(pk=second_created.data["id"])
    repeated_answers = [
        {
            "question_id": question["id"],
            "selected_option_id": (
                wrong_option
                if question["id"] == first_question["id"]
                else question["correct_option_id"]
            ),
        }
        for question in second_card.questions
    ]
    repeated = api.post(
        f"{root(study_context)}/answer-cards/{second_card.id}/submit",
        {"answers": repeated_answers},
        format="json",
    )

    assert repeated.status_code == 200, repeated.data
    assert MistakeRecord.objects.filter(
        profile=card.profile,
        problem__source="answer_card",
        problem__analysis__question_id=first_question["id"],
    ).count() == 1
    mistake.refresh_from_db()
    assert mistake.mastery == 10


@pytest.mark.django_db
def test_answer_card_rejects_tampering_and_curriculum_mismatch(study_context):
    assert create_profile(study_context).status_code == 200
    api, created = create_answer_card(study_context)
    assert created.status_code == 201, created.data
    card = AnswerCard.objects.get(pk=created.data["id"])
    invalid = api.post(
        f"{root(study_context)}/answer-cards/{card.id}/submit",
        {
            "answers": [
                {"question_id": item["id"], "selected_option_id": "A"}
                for item in card.questions[:-1]
            ]
        },
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.data["detail"] == "请完成答题卡中的全部题目。"

    duplicated_answers = [
        {"question_id": item["id"], "selected_option_id": "A"}
        for item in card.questions
    ]
    duplicated_answers[-1]["question_id"] = duplicated_answers[0]["question_id"]
    duplicated = api.post(
        f"{root(study_context)}/answer-cards/{card.id}/submit",
        {"answers": duplicated_answers},
        format="json",
    )
    assert duplicated.status_code == 400
    assert duplicated.data["detail"] == "同一道题不能重复提交。"

    mismatch = api.post(
        f"{root(study_context)}/answer-cards",
        {
            "subject": "math",
            "curriculum_version": "pep-history-current",
            "knowledge_point_code": "history.pep.outline-1.origins-qin-han",
        },
        format="json",
    )
    assert mismatch.status_code == 400
    assert mismatch.data["detail"] == "学科与教材版本不匹配。"


@pytest.mark.django_db
def test_curriculum_reports_missing_teaching_data_as_unavailable(study_context):
    assert create_profile(study_context).status_code == 200
    with TemporaryDirectory() as directory, override_settings(TEACHING_DATA_ROOT=directory):
        response = client(study_context["student"]).get(
            f"{root(study_context)}/curriculum",
            {"subject": "math", "curriculum_version": "xj-math-current"},
        )
    assert response.status_code == 503
    assert "无法读取教学数据" in response.data["detail"]


@pytest.mark.django_db
def test_multi_subject_profile_uses_focus_weighting_and_daily_budget(study_context):
    response = client(study_context["student"]).put(
        f"{root(study_context)}/profile",
        {
            "grade_stage": GradeStage.HIGH_1,
            "subjects": [Subject.MATH, Subject.PHYSICS, Subject.ENGLISH],
            "focus_subjects": [Subject.MATH, Subject.PHYSICS],
            "daily_minutes": 45,
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["focus_subjects"] == [Subject.MATH, Subject.PHYSICS]
    assert {item["subject"] for item in response.data["enrollments"]} == {
        Subject.MATH, Subject.PHYSICS, Subject.ENGLISH,
    }
    assert all(not item["setup_completed"] for item in response.data["enrollments"])

    profile = StudyProfile.objects.get(student=study_context["student"])
    tasks = list(profile.tasks.order_by("scheduled_for", "created_at"))
    assert {task.subject for task in tasks} == {
        Subject.MATH, Subject.PHYSICS, Subject.ENGLISH,
    }
    per_day = {}
    for task in tasks:
        per_day.setdefault(task.scheduled_for, []).append(task)
    assert len(per_day) == 7
    assert all(len({task.subject for task in day}) <= 2 for day in per_day.values())
    assert all(sum(task.duration_minutes for task in day) <= 45 for day in per_day.values())
    counts = {
        subject: sum(task.subject == subject for task in tasks)
        for subject in (Subject.MATH, Subject.PHYSICS, Subject.ENGLISH)
    }
    assert counts[Subject.MATH] > counts[Subject.ENGLISH]
    assert counts[Subject.PHYSICS] > counts[Subject.ENGLISH]

    completed = tasks[0]
    completed.status = StudyTask.Status.COMPLETED
    completed.completed_at = timezone.now()
    completed.save(update_fields=("status", "completed_at", "updated_at"))
    changed = client(study_context["student"]).put(
        f"{root(study_context)}/profile",
        {
            "grade_stage": GradeStage.HIGH_1,
            "subjects": [Subject.MATH, Subject.ENGLISH],
            "focus_subjects": [Subject.ENGLISH],
            "daily_minutes": 30,
        },
        format="json",
    )
    assert changed.status_code == 200, changed.data
    assert StudyTask.objects.filter(pk=completed.pk, status=StudyTask.Status.COMPLETED).exists()
    profile.refresh_from_db()
    assert not profile.enrollments.get(subject=Subject.PHYSICS).is_active


@pytest.mark.django_db
def test_progressive_enrollment_rejects_invalid_scores_without_saving(study_context):
    assert client(study_context["student"]).put(
        f"{root(study_context)}/profile",
        {
            "grade_stage": GradeStage.HIGH_2,
            "subjects": [Subject.MATH, Subject.PHYSICS],
            "focus_subjects": [Subject.MATH],
            "daily_minutes": 60,
        },
        format="json",
    ).status_code == 200
    student = client(study_context["student"])
    updated = student.patch(
        f"{root(study_context)}/enrollments/{Subject.PHYSICS}",
        {
            "curriculum_version": "人教版",
            "current_chapter": "运动和力",
            "weak_topics": ["受力分析"],
            "latest_score": 82,
            "target_score": 105,
        },
        format="json",
    )
    assert updated.status_code == 200, updated.data
    assert updated.data["setup_completed"] is True

    rejected = student.patch(
        f"{root(study_context)}/enrollments/{Subject.PHYSICS}",
        {"latest_score": 110, "target_score": 90},
        format="json",
    )
    assert rejected.status_code == 400
    enrollment = StudyProfile.objects.get(
        student=study_context["student"]
    ).enrollments.get(subject=Subject.PHYSICS, is_active=True)
    assert float(enrollment.latest_score) == 82
    assert float(enrollment.target_score) == 105


@pytest.mark.django_db
def test_tutor_selector_and_sessions_only_use_deployed_standard_tutors(study_context):
    assert create_profile(study_context).status_code == 200
    tutor = deploy_subject_tutor(study_context, Subject.MATH)
    unrelated = Agent.objects.create(
        organization=study_context["organization"],
        category=tutor.category,
        name="其他智能体",
        slug="not-a-school-tutor",
        description="不应出现在学科老师列表",
        created_by=study_context["student"],
        is_public=False,
    )
    student = client(study_context["student"])

    tutors = student.get(f"{root(study_context)}/tutors")
    assert tutors.status_code == 200, tutors.data
    assert [item["id"] for item in tutors.data] == [tutor.id]

    created = student.post(
        f"{root(study_context)}/tutor-sessions",
        {"mode": "chat", "subject": Subject.MATH, "agent_id": tutor.id},
        format="json",
    )
    assert created.status_code == 201, created.data
    conversation = Conversation.objects.get(pk=created.data["conversation"]["id"])
    assert conversation.agent == tutor
    assert conversation.agent_locked is True

    switched = student.post(
        f"/api/v1/conversations/{conversation.id}/send_message/",
        {"content": "换一个老师", "agent_id": unrelated.id},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(study_context["organization"].id),
        HTTP_IDEMPOTENCY_KEY="locked-study-tutor",
    )
    assert switched.status_code == 400
    assert "固定老师" in str(switched.data["agent_id"])

    history = student.get(f"{root(study_context)}/tutor-sessions")
    assert history.status_code == 200
    assert history.data[0]["id"] == conversation.id
    assert history.data[0]["subject"] == Subject.MATH


@pytest.mark.django_db
def test_photo_tutor_rejects_unreadable_or_unsupported_images(study_context):
    assert create_profile(study_context).status_code == 200
    tutor = deploy_subject_tutor(study_context, Subject.MATH)
    response = client(study_context["student"]).post(
        f"{root(study_context)}/tutor-sessions",
        {
            "mode": "photo",
            "subject": Subject.MATH,
            "agent_id": tutor.id,
            "source_image": SimpleUploadedFile(
                "broken.png", b"not-an-image", content_type="image/png"
            ),
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert not Problem.objects.filter(profile__student=study_context["student"]).exists()


@pytest.mark.django_db
def test_photo_tutor_atomically_links_problem_message_attachment_and_run(study_context):
    assert create_profile(study_context).status_code == 200
    tutor = deploy_subject_tutor(study_context, Subject.MATH)
    with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
        response = client(study_context["student"]).post(
            f"{root(study_context)}/tutor-sessions",
            {
                "mode": "photo",
                "subject": Subject.MATH,
                "agent_id": tutor.id,
                "source_image": image_file(),
            },
            format="multipart",
        )

        assert response.status_code == 201, response.data
        problem = Problem.objects.get(pk=response.data["problem"]["id"])
        attachment = MessageAttachment.objects.get(
            message__conversation_id=response.data["conversation"]["id"]
        )
        assert problem.source_attachment == attachment
        assert problem.source_image.name == attachment.file.name
        assert attachment.message.role == "user"
        run = Run.objects.get(pk=response.data["run_id"])
        assert run.input["attachments"] == [{
            "id": str(attachment.id),
            "name": attachment.original_name,
            "content_type": attachment.content_type,
            "byte_size": attachment.byte_size,
            "path": attachment.file.path,
        }]


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

    image = image_file()
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
def test_mistakes_can_be_filtered_by_record_date(study_context):
    assert create_profile(study_context).status_code == 200
    student = client(study_context["student"])
    endpoint = f"{root(study_context)}/mistakes"

    yesterday_response = student.post(
        endpoint,
        {"problem_text": "昨天的错题", "cause": "concept"},
        format="multipart",
    )
    today_response = student.post(
        endpoint,
        {"problem_text": "今天的错题", "cause": "calculation"},
        format="multipart",
    )
    assert yesterday_response.status_code == 201
    assert today_response.status_code == 201

    current_date = timezone.localdate()
    previous_month_date = (current_date.replace(day=1) - timedelta(days=1)).replace(day=15)
    previous_month = timezone.make_aware(
        datetime.combine(previous_month_date, time(hour=12))
    )
    MistakeRecord.objects.filter(pk=yesterday_response.data["id"]).update(
        created_at=previous_month
    )

    today_result = student.get(
        endpoint,
        {"subject": "math", "date": current_date.isoformat()},
    )
    yesterday_result = student.get(
        endpoint,
        {"subject": "math", "date": previous_month_date.isoformat()},
    )

    assert today_result.status_code == 200
    assert [item["id"] for item in today_result.data] == [today_response.data["id"]]
    assert yesterday_result.status_code == 200
    assert [item["id"] for item in yesterday_result.data] == [yesterday_response.data["id"]]
    current_month_result = student.get(
        endpoint, {"subject": "math", "month": current_date.strftime("%Y-%m")}
    )
    previous_month_result = student.get(
        endpoint,
        {"subject": "math", "month": previous_month_date.strftime("%Y-%m")},
    )
    assert [item["id"] for item in current_month_result.data] == [today_response.data["id"]]
    assert [item["id"] for item in previous_month_result.data] == [
        yesterday_response.data["id"]
    ]
    week_start = current_date - timedelta(days=current_date.weekday())
    week_result = student.get(
        endpoint,
        {
            "subject": "math",
            "start_date": week_start.isoformat(),
            "end_date": (week_start + timedelta(days=6)).isoformat(),
        },
    )
    assert [item["id"] for item in week_result.data] == [today_response.data["id"]]
    assert len(student.get(endpoint, {"subject": "math"}).data) == 2
    assert student.get(endpoint, {"date": "2026-99-99"}).status_code == 400
    assert student.get(endpoint, {"month": "2026-13"}).status_code == 400
    assert student.get(
        endpoint,
        {"date": current_date.isoformat(), "month": current_date.strftime("%Y-%m")},
    ).status_code == 400
    assert student.get(endpoint, {"start_date": current_date.isoformat()}).status_code == 400


@pytest.mark.django_db
def test_mistake_check_in_is_daily_idempotent_and_reports_streak(study_context):
    assert create_profile(study_context).status_code == 200
    student = client(study_context["student"])
    profile = StudyProfile.objects.get(student=study_context["student"])
    today = timezone.localdate()
    for days_ago in (2, 1):
        MistakeCheckIn.objects.create(
            organization=study_context["organization"],
            profile=profile,
            subject="math",
            checked_on=today - timedelta(days=days_ago),
        )

    mistakes_endpoint = f"{root(study_context)}/mistakes"
    first = student.post(
        mistakes_endpoint,
        {"problem_text": "第一道今日错题", "cause": "concept"},
        format="multipart",
    )
    second = student.post(
        mistakes_endpoint,
        {"problem_text": "第二道今日错题", "cause": "calculation"},
        format="multipart",
    )
    endpoint = f"{root(study_context)}/mistake-check-ins"
    summary = student.get(endpoint, {"subject": "math"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert summary.status_code == 200
    assert summary.data["checked_in_today"] is True
    assert summary.data["streak"] == 3
    assert len(summary.data["check_ins"]) == 3
    assert MistakeCheckIn.objects.filter(profile=profile, subject="math").count() == 3
    assert student.post(endpoint, {"subject": "math"}, format="json").status_code == 405
    assert student.get(endpoint, {"subject": "not-a-subject"}).status_code == 400


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
    assert conversation.title.startswith("数学 ·")
    assert conversation.process_id == f"study-tutor:{problem.id}"
    assert conversation.agent_locked is True
    assert problem.latest_run_id == created_runs[1].id
    assert list(Message.objects.filter(conversation=conversation).values_list(
        "role", "content",
    )) == [
        ("user", "请分析这道数学题：\n求函数 f(x)=x² 的单调区间。"),
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
def test_weekly_report_returns_overall_metrics_and_subject_cards(study_context):
    profile_response = client(study_context["student"]).put(
        f"{root(study_context)}/profile",
        {
            "grade_stage": GradeStage.HIGH_3,
            "subjects": [Subject.MATH, Subject.ENGLISH],
            "focus_subjects": [Subject.MATH],
            "daily_minutes": 60,
        },
        format="json",
    )
    assert profile_response.status_code == 200, profile_response.data

    response = client(study_context["student"]).post(
        f"{root(study_context)}/reports", {}, format="json"
    )

    assert response.status_code == 201, response.data
    assert set(response.data) == {"overall_metrics", "subjects"}
    assert {item["subject"] for item in response.data["subjects"]} == {
        Subject.MATH, Subject.ENGLISH,
    }
    assert response.data["overall_metrics"]["task_total"] == sum(
        item["metrics"]["task_total"] for item in response.data["subjects"]
    )
    fetched = client(study_context["student"]).get(
        f"{root(study_context)}/reports?aggregate=1"
    )
    assert fetched.status_code == 200
    assert len(fetched.data["subjects"]) == 2


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

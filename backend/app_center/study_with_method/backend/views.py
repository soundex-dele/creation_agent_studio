from __future__ import annotations

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.tenancy.permissions import HasPathOrganization
from apps.agents.high_school_tutors import TUTOR_DEFINITION_BY_SUBJECT
from apps.agents.models import Agent
from apps.conversations.models import Conversation
from apps.conversations.serializers import ConversationListSerializer
from modules.catalog.models import AgentDeployment

from .models import (
    GuardianLink,
    CurriculumNode,
    MistakeRecord,
    Problem,
    ReviewSchedule,
    StudyProfile,
    StudyTask,
    StudyWorkspace,
    Subject,
    SubjectEnrollment,
    WeeklyReport,
    WeeklyQuiz,
)
from .serializers import (
    AnswerCardCreateSerializer,
    AnswerCardSerializer,
    AnswerCardSubmitSerializer,
    AttemptInputSerializer,
    AttemptSerializer,
    EnrollmentSerializer,
    GuardianLinkSerializer,
    ManualMistakeInputSerializer,
    MasterySerializer,
    MistakeCheckInInputSerializer,
    MistakeCheckInSerializer,
    MistakeListQuerySerializer,
    MistakeSerializer,
    MistakeUpdateSerializer,
    ProblemInputSerializer,
    ProblemSerializer,
    ProfileInputSerializer,
    ProfileSerializer,
    ReviewSerializer,
    StudyTaskSerializer,
    WeeklyReportSerializer,
    WeeklyQuizSerializer,
)
from .services import (
    active_enrollment,
    build_answer_card,
    build_weekly_report,
    build_weekly_quiz,
    complete_review,
    generate_week_plan,
    generate_multi_subject_week_plan,
    record_attempt,
    reschedule_overdue_tasks,
    resolve_curriculum_node,
    start_tutor_run,
    submit_answer_card,
    submit_weekly_quiz,
)
from .strategies import get_subject_strategy
from .catalog import catalog_payload
from .teaching_data import TeachingDataError, public_curriculum_tree


class StudyAPIView(APIView):
    permission_classes = (IsAuthenticated, HasPathOrganization)

    def workspace(self, organization_id, application_id):
        return StudyWorkspace.objects.for_organization(organization_id).filter(
            application_id=application_id,
            application__organization_id=organization_id,
            application__is_active=True,
        ).first()

    def own_profile(self, request, organization_id, application_id):
        workspace = self.workspace(organization_id, application_id)
        if workspace is None:
            return None
        return StudyProfile.objects.for_organization(organization_id).filter(
            workspace=workspace, student=request.user
        ).first()

    def require_profile(self, request, organization_id, application_id):
        profile = self.own_profile(request, organization_id, application_id)
        if profile is None:
            return None, Response(
                {"detail": "请先完成学习档案。"}, status=status.HTTP_404_NOT_FOUND
            )
        return profile, None


class CatalogView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        if self.workspace(organization_id, application_id) is None:
            return Response({"detail": "应用尚未安装。"}, status=404)
        return Response(catalog_payload())


class CurriculumView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        subject = request.query_params.get("subject", "")
        curriculum_version = request.query_params.get("curriculum_version", "")
        if not subject or not curriculum_version:
            return Response(
                {"detail": "subject 和 curriculum_version 为必填项。"}, status=400
            )
        if active_enrollment(profile, subject) is None:
            return Response({"detail": "未启用该学科。"}, status=400)
        try:
            tree = public_curriculum_tree(
                subject=subject, curriculum_id=curriculum_version
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except TeachingDataError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response(tree)


class EnrollmentDetailView(StudyAPIView):
    def patch(self, request, organization_id, application_id, subject):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        if subject not in Subject.values:
            return Response({"subject": "未知学科。"}, status=404)
        enrollment = profile.enrollments.filter(subject=subject, is_active=True).first()
        if enrollment is None:
            return Response({"detail": "未启用该学科。"}, status=404)
        allowed = {
            "curriculum_version", "current_chapter", "weak_topics",
            "latest_score", "target_score",
        }
        serializer = EnrollmentSerializer(enrollment, data={
            key: value for key, value in request.data.items() if key in allowed
        }, partial=True)
        serializer.is_valid(raise_exception=True)
        latest_score = serializer.validated_data.get(
            "latest_score", enrollment.latest_score
        )
        target_score = serializer.validated_data.get(
            "target_score", enrollment.target_score
        )
        if (
            latest_score is not None
            and target_score is not None
            and target_score < latest_score
        ):
            return Response({"target_score": "目标分数不能低于最近成绩。"}, status=400)
        updated = serializer.save()
        generate_multi_subject_week_plan(profile, replace_pending=True)
        return Response(EnrollmentSerializer(updated).data)


def _available_tutors(organization_id):
    deployment_agent_ids = AgentDeployment.objects.filter(
        organization_id=organization_id
    ).values_list("agent_id", flat=True)
    agents = Agent.objects.filter(
        organization_id=organization_id,
        is_active=True,
        id__in=deployment_agent_ids,
        slug__in=[item.slug for item in TUTOR_DEFINITION_BY_SUBJECT.values()],
    )
    by_slug = {agent.slug: agent for agent in agents}
    return [
        (subject, by_slug[definition.slug])
        for subject, definition in TUTOR_DEFINITION_BY_SUBJECT.items()
        if definition.slug in by_slug
    ]


class TutorListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        if self.workspace(organization_id, application_id) is None:
            return Response({"detail": "应用尚未安装。"}, status=404)
        return Response([
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "subject": subject,
                "subject_label": dict(Subject.choices)[subject],
            }
            for subject, agent in _available_tutors(organization_id)
        ])


class TutorSessionListView(StudyAPIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        conversations = Conversation.objects.filter(
            organization_id=organization_id,
            user=request.user,
            process_id__startswith="study-tutor:",
        ).select_related("agent")[:20]
        subject_by_slug = {
            definition.slug: subject
            for subject, definition in TUTOR_DEFINITION_BY_SUBJECT.items()
        }
        return Response([
            {
                **ConversationListSerializer(item, context={"request": request}).data,
                "subject": subject_by_slug.get(item.agent.slug if item.agent else "", ""),
            }
            for item in conversations
        ])

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        subject = str(request.data.get("subject") or "")
        mode = str(request.data.get("mode") or "chat")
        if subject not in Subject.values:
            return Response({"subject": "请选择辅导学科。"}, status=400)
        if not profile.enrollments.filter(subject=subject, is_active=True).exists():
            return Response({"subject": "请先在学习档案中启用该学科。"}, status=400)
        definition = TUTOR_DEFINITION_BY_SUBJECT[subject]
        try:
            requested_agent_id = int(request.data.get("agent_id") or 0)
        except (TypeError, ValueError):
            requested_agent_id = 0
        tutor = next((
            agent for tutor_subject, agent in _available_tutors(organization_id)
            if tutor_subject == subject and (not requested_agent_id or agent.id == requested_agent_id)
        ), None)
        if tutor is None or tutor.slug != definition.slug:
            return Response({"agent_id": "该学科老师尚未部署。"}, status=409)

        profile.last_tutor_subject = subject
        profile.save(update_fields=("last_tutor_subject", "updated_at"))
        if mode == "chat":
            conversation = Conversation.objects.create(
                user=request.user,
                organization=request.organization,
                title=f"{dict(Subject.choices)[subject]}辅导",
                agent=tutor,
                process_id=f"study-tutor:{uuid.uuid4()}",
                agent_locked=True,
            )
            return Response({
                "conversation": ConversationListSerializer(
                    conversation, context={"request": request}
                ).data,
                "subject": subject,
                "problem": None,
                "run_id": None,
            }, status=201)

        if mode != "photo":
            return Response({"mode": "辅导方式必须是 photo 或 chat。"}, status=400)
        serializer = ProblemInputSerializer(data={
            "subject": subject,
            "grade_stage": profile.grade_stage,
            "source_image": request.data.get("source_image"),
            "source": "camera",
        })
        serializer.is_valid(raise_exception=True)
        problem = Problem.objects.create(
            organization=request.organization,
            profile=profile,
            subject=subject,
            grade_stage=profile.grade_stage,
            source_image=serializer.validated_data["source_image"],
            source="camera",
            status=Problem.Status.NEEDS_CONFIRMATION,
            analysis={"recognition": "conversation"},
        )
        try:
            run = start_tutor_run(
                problem=problem,
                actor=request.user,
                operation="analyze",
                agent_id=tutor.id,
            )
        except Exception as exc:
            problem.analysis = {**problem.analysis, "run_error": str(exc)}
            problem.save(update_fields=("analysis", "updated_at"))
            run = None
        conversation = Conversation.objects.get(pk=problem.conversation_id) if problem.conversation_id else None
        return Response({
            "conversation": ConversationListSerializer(
                conversation, context={"request": request}
            ).data if conversation else None,
            "subject": subject,
            "problem": ProblemSerializer(problem, context={"request": request}).data,
            "run_id": str(run.id) if run else None,
        }, status=201 if conversation else 503)


def _report_summary(reports):
    serialized = WeeklyReportSerializer(list(reports), many=True).data
    latest_by_subject = {}
    for report in serialized:
        latest_by_subject.setdefault(report["subject"], report)
    subject_reports = list(latest_by_subject.values())
    metric_names = ("task_total", "task_completed", "planned_minutes", "mistake_count", "due_review_count")
    overall = {
        key: sum(int((item.get("metrics") or {}).get(key) or 0) for item in subject_reports)
        for key in metric_names
    }
    overall["completion_rate"] = round(
        100 * overall["task_completed"] / overall["task_total"]
    ) if overall["task_total"] else 0
    rates = [
        int((item.get("metrics") or {}).get("correct_rate") or 0)
        for item in subject_reports
        if (item.get("metrics") or {}).get("attempt_total")
    ]
    overall["correct_rate"] = round(sum(rates) / len(rates)) if rates else 0
    return {"overall_metrics": overall, "subjects": subject_reports}


class DashboardView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        workspace = self.workspace(organization_id, application_id)
        if workspace is None:
            return Response({"detail": "应用尚未安装。"}, status=404)
        profile = self.own_profile(request, organization_id, application_id)
        if profile is None:
            links = GuardianLink.objects.for_organization(organization_id).filter(
                guardian=request.user,
                is_active=True,
                profile__workspace=workspace,
            ).select_related("profile")
            if links.exists():
                reports = WeeklyReport.objects.for_organization(organization_id).filter(
                    profile_id__in=links.values_list("profile_id", flat=True)
                ).select_related("profile")[:12]
                return Response({
                    "mode": "guardian",
                    "reports": WeeklyReportSerializer(reports, many=True).data,
                })
            return Response({
                "mode": "onboarding",
                "enabled_subjects": workspace.enabled_subjects,
            })

        enrollments = list(profile.enrollments.filter(is_active=True))
        if enrollments:
            reschedule_overdue_tasks(profile)
            generate_multi_subject_week_plan(profile)
        today = timezone.localdate()
        tasks = profile.tasks.filter(scheduled_for=today)
        reviews = profile.review_schedules.filter(next_review_at__lte=timezone.now())
        latest_report = profile.weekly_reports.first()
        return Response({
            "mode": "student",
            "profile": ProfileSerializer(profile, context={"request": request}).data,
            "enrollments": EnrollmentSerializer(enrollments, many=True).data,
            "today": str(today),
            "tasks": StudyTaskSerializer(tasks, many=True).data,
            "due_reviews": ReviewSerializer(reviews[:5], many=True, context={"request": request}).data,
            "due_review_count": reviews.count(),
            "mistake_count": profile.mistakes.count(),
            "masteries": MasterySerializer(profile.masteries.order_by("score")[:5], many=True).data,
            "latest_report": WeeklyReportSerializer(latest_report).data if latest_report else None,
            "stats_by_subject": [
                {
                    "subject": enrollment.subject,
                    "subject_label": enrollment.get_subject_display(),
                    "task_count": tasks.filter(subject=enrollment.subject).count(),
                    "completed_count": tasks.filter(
                        subject=enrollment.subject,
                        status=StudyTask.Status.COMPLETED,
                    ).count(),
                    "mistake_count": profile.mistakes.filter(subject=enrollment.subject).count(),
                }
                for enrollment in enrollments
            ],
        })


class ProfileView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        return Response(ProfileSerializer(profile, context={"request": request}).data)

    def put(self, request, organization_id, application_id):
        workspace = self.workspace(organization_id, application_id)
        if workspace is None:
            return Response({"detail": "应用尚未安装。"}, status=404)
        serializer = ProfileInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        unavailable = [
            subject for subject in data["subjects"]
            if subject not in (workspace.enabled_subjects or [])
        ]
        if unavailable:
            return Response(
                {"subjects": f"当前工作区未开放：{', '.join(unavailable)}。"},
                status=400,
            )
        with transaction.atomic():
            existing_profile = StudyProfile.objects.filter(
                organization=request.organization,
                workspace=workspace,
                student=request.user,
            ).first()
            profile, _ = StudyProfile.objects.update_or_create(
                organization=request.organization,
                workspace=workspace,
                student=request.user,
                defaults={
                    "display_name": data.get(
                        "display_name",
                        existing_profile.display_name if existing_profile else "",
                    ),
                    "region": data.get(
                        "region", existing_profile.region if existing_profile else ""
                    ),
                    "primary_subject": data["subjects"][0],
                    "grade_stage": data["grade_stage"],
                    "daily_minutes": data["daily_minutes"],
                    "focus_subjects": data["focus_subjects"],
                    "last_tutor_subject": data["subjects"][0],
                    "latest_score": data.get(
                        "latest_score",
                        existing_profile.latest_score if existing_profile else None,
                    ),
                    "target_score": data.get(
                        "target_score",
                        existing_profile.target_score if existing_profile else None,
                    ),
                    "onboarding_completed": True,
                },
            )
            profile.enrollments.exclude(
                subject__in=data["subjects"], grade_stage=data["grade_stage"]
            ).update(is_active=False)
            for index, subject in enumerate(data["subjects"]):
                SubjectEnrollment.objects.update_or_create(
                    organization=request.organization,
                    profile=profile,
                    subject=subject,
                    grade_stage=data["grade_stage"],
                    defaults={
                        "curriculum_version": data.get("curriculum_version", "") if index == 0 else "",
                        "current_chapter": data.get("current_chapter", "") if index == 0 else "",
                        "weak_topics": data.get("weak_topics", []) if index == 0 else [],
                        "latest_score": data.get("latest_score") if index == 0 else None,
                        "target_score": data.get("target_score") if index == 0 else None,
                        "is_active": True,
                    },
                )
            generate_multi_subject_week_plan(profile, replace_pending=True)
        return Response(ProfileSerializer(profile, context={"request": request}).data)


class TaskListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        reschedule_overdue_tasks(profile)
        tasks = profile.tasks.all()
        subject = request.query_params.get("subject")
        if subject:
            get_subject_strategy(subject)
            tasks = tasks.filter(subject=subject)
        scheduled_for = request.query_params.get("date")
        if scheduled_for:
            tasks = tasks.filter(scheduled_for=scheduled_for)
        return Response(StudyTaskSerializer(tasks[:100], many=True).data)


class TaskDetailView(StudyAPIView):
    def patch(self, request, organization_id, application_id, task_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        task = profile.tasks.filter(pk=task_id).first()
        if task is None:
            return Response({"detail": "学习任务不存在。"}, status=404)
        next_status = request.data.get("status")
        if next_status not in (StudyTask.Status.COMPLETED, StudyTask.Status.SKIPPED):
            return Response({"status": "只能完成或跳过任务。"}, status=400)
        task.status = next_status
        task.completed_at = timezone.now() if next_status == StudyTask.Status.COMPLETED else None
        task.save(update_fields=("status", "completed_at", "updated_at"))
        return Response(StudyTaskSerializer(task).data)


class ProblemListView(StudyAPIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problems = profile.problems.select_related("knowledge_point").prefetch_related("attempts")
        return Response(
            ProblemSerializer(problems[:100], many=True, context={"request": request}).data
        )

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        serializer = ProblemInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        text = data.get("problem_text", "").strip()
        strategy = get_subject_strategy(data["subject"])
        knowledge = resolve_curriculum_node(
            data["subject"], strategy.detect_topic(text), data["grade_stage"]
        ) if text else None
        problem = Problem.objects.create(
            organization=request.organization,
            profile=profile,
            subject=data["subject"],
            grade_stage=data["grade_stage"],
            source_image=data.get("source_image") or "",
            original_text=text,
            confirmed_text=text,
            source=data["source"],
            status=Problem.Status.READY if text else Problem.Status.NEEDS_CONFIRMATION,
            knowledge_point=knowledge,
            analysis={"strategy_version": strategy.version, "recognition": "manual" if text else "pending"},
        )
        run = None
        if text or problem.source_image:
            try:
                run = start_tutor_run(problem=problem, actor=request.user, operation="analyze")
            except Exception as exc:  # The manual workflow must remain available without an AI provider.
                problem.analysis = {**problem.analysis, "run_error": str(exc)}
                problem.save(update_fields=("analysis", "updated_at"))
        response = ProblemSerializer(problem, context={"request": request}).data
        response["tutor_run_id"] = str(run.id) if run else None
        return Response(response, status=201)


class ProblemDetailView(StudyAPIView):
    def _problem(self, profile, problem_id):
        return profile.problems.select_related("knowledge_point").prefetch_related("attempts").filter(pk=problem_id).first()

    def get(self, request, organization_id, application_id, problem_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problem = self._problem(profile, problem_id)
        if problem is None:
            return Response({"detail": "题目不存在。"}, status=404)
        return Response(ProblemSerializer(problem, context={"request": request}).data)

    def patch(self, request, organization_id, application_id, problem_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problem = self._problem(profile, problem_id)
        if problem is None:
            return Response({"detail": "题目不存在。"}, status=404)
        text = str(request.data.get("confirmed_text") or "").strip()
        if not text:
            return Response({"confirmed_text": "请确认题目文字。"}, status=400)
        strategy = get_subject_strategy(problem.subject)
        problem.confirmed_text = text
        problem.status = Problem.Status.READY
        problem.knowledge_point = resolve_curriculum_node(
            problem.subject, strategy.detect_topic(text), problem.grade_stage
        )
        problem.analysis = {**problem.analysis, "recognition": "confirmed", "strategy_version": strategy.version}
        problem.save(update_fields=("confirmed_text", "status", "knowledge_point", "analysis", "updated_at"))
        try:
            start_tutor_run(problem=problem, actor=request.user, operation="analyze")
        except Exception as exc:
            problem.analysis = {**problem.analysis, "run_error": str(exc)}
            problem.save(update_fields=("analysis", "updated_at"))
        return Response(ProblemSerializer(problem, context={"request": request}).data)

    def delete(self, request, organization_id, application_id, problem_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problem = profile.problems.filter(pk=problem_id).first()
        if problem is None:
            return Response({"detail": "题目不存在。"}, status=404)
        if problem.source_image:
            problem.source_image.delete(save=False)
        problem.delete()
        return Response(status=204)


class ProblemHintView(StudyAPIView):
    def post(self, request, organization_id, application_id, problem_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problem = profile.problems.filter(pk=problem_id).first()
        if problem is None:
            return Response({"detail": "题目不存在。"}, status=404)
        if problem.status == Problem.Status.NEEDS_CONFIRMATION:
            return Response({"detail": "请先确认题目文字。"}, status=409)
        requested = request.data.get("hint_level")
        level = int(requested) if requested is not None else problem.max_hint_level + 1
        level = max(1, min(level, 4))
        thought = str(request.data.get("student_thought") or "")
        strategy = get_subject_strategy(problem.subject)
        local_hint = strategy.hint(problem.confirmed_text, level, thought)
        problem.max_hint_level = max(problem.max_hint_level, level)
        problem.save(update_fields=("max_hint_level", "updated_at"))
        run = None
        try:
            run = start_tutor_run(
                problem=problem,
                actor=request.user,
                operation="solution" if level == 4 else "hint",
                student_thought=thought,
                hint_level=level,
            )
        except Exception as exc:
            local_hint["run_error"] = str(exc)
        local_hint["tutor_run_id"] = str(run.id) if run else None
        return Response(local_hint)


class ProblemVariantView(StudyAPIView):
    def post(self, request, organization_id, application_id, problem_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problem = profile.problems.filter(pk=problem_id).first()
        if problem is None:
            return Response({"detail": "题目不存在。"}, status=404)
        if problem.status != Problem.Status.COMPLETED:
            return Response({"detail": "完成原题后才能生成同类题。"}, status=409)
        try:
            run = start_tutor_run(
                problem=problem,
                actor=request.user,
                operation="variant",
                hint_level=4,
            )
        except Exception as exc:
            return Response({
                "tutor_run_id": None,
                "validation_status": "unavailable",
                "detail": str(exc),
            }, status=503)
        return Response({
            "tutor_run_id": str(run.id) if run else None,
            "validation_status": "pending_independent_check" if run else "unavailable",
        }, status=202 if run else 503)


class AttemptCreateView(StudyAPIView):
    def post(self, request, organization_id, application_id, problem_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        problem = profile.problems.filter(pk=problem_id).first()
        if problem is None:
            return Response({"detail": "题目不存在。"}, status=404)
        serializer = AttemptInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attempt = record_attempt(
            problem=problem,
            response=data.get("response", ""),
            thought=data.get("student_thought", ""),
            duration_seconds=data["duration_seconds"],
            is_correct=data.get("is_correct"),
        )
        return Response(AttemptSerializer(attempt).data, status=201)


class MistakeListView(StudyAPIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        mistakes = profile.mistakes.select_related(
            "problem", "knowledge_point", "review_schedule"
        ).prefetch_related("problem__attempts")
        query = MistakeListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        if subject := query.validated_data.get("subject"):
            mistakes = mistakes.filter(subject=subject)
        if recorded_on := query.validated_data.get("date"):
            mistakes = mistakes.filter(created_at__date=recorded_on)
        if month := query.validated_data.get("month"):
            year, month_number = (int(part) for part in month.split("-"))
            mistakes = mistakes.filter(
                created_at__year=year,
                created_at__month=month_number,
            )
        if start_date := query.validated_data.get("start_date"):
            mistakes = mistakes.filter(
                created_at__date__gte=start_date,
                created_at__date__lte=query.validated_data["end_date"],
            )
        return Response(MistakeSerializer(mistakes, many=True, context={"request": request}).data)

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        serializer = ManualMistakeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        problem_text = data.get("problem_text", "").strip()
        knowledge_summary = data.get("knowledge_summary", "").strip()
        strategy = get_subject_strategy(data["subject"])
        knowledge_point = None
        if knowledge_summary:
            knowledge_point = CurriculumNode.objects.filter(
                subject=data["subject"],
                grade_stage=data["grade_stage"],
                node_type=CurriculumNode.NodeType.KNOWLEDGE_POINT,
            ).filter(
                Q(code__iexact=knowledge_summary) | Q(name__iexact=knowledge_summary)
            ).first()
        if knowledge_point is None and (problem_text or knowledge_summary):
            knowledge_point = resolve_curriculum_node(
                data["subject"],
                strategy.detect_topic(f"{knowledge_summary}\n{problem_text}".strip()),
                data["grade_stage"],
            )

        with transaction.atomic():
            problem = Problem.objects.create(
                organization=request.organization,
                profile=profile,
                subject=data["subject"],
                grade_stage=data["grade_stage"],
                source_image=data.get("source_image") or "",
                original_text=problem_text,
                confirmed_text=problem_text,
                source="manual_import",
                status=Problem.Status.READY,
                knowledge_point=knowledge_point,
                analysis={
                    "manual_mistake_import": True,
                    "strategy_version": strategy.version,
                },
                answer_key={"answer": data.get("correct_answer", "").strip()},
            )
            record_attempt(
                problem=problem,
                response="",
                thought=data.get("notes", "").strip(),
                duration_seconds=0,
                is_correct=False,
            )
            mistake = problem.mistake
            mistake.cause = data["cause"]
            mistake.knowledge_summary = knowledge_summary
            mistake.notes = data.get("notes", "").strip()
            mistake.correct_answer = data.get("correct_answer", "").strip()
            mistake.similar_problem_types = data.get("similar_problem_types", [])
            mistake.save(update_fields=(
                "cause", "knowledge_summary", "notes", "correct_answer",
                "similar_problem_types", "updated_at",
            ))
        return Response(
            MistakeSerializer(mistake, context={"request": request}).data,
            status=201,
        )


class MistakeDetailView(StudyAPIView):
    def patch(self, request, organization_id, application_id, mistake_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        mistake = profile.mistakes.filter(pk=mistake_id).first()
        if mistake is None:
            return Response({"detail": "错题不存在。"}, status=404)
        serializer = MistakeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cause = data.get("cause", mistake.cause)
        allowed = set(get_subject_strategy(mistake.subject).mistake_causes)
        if cause not in allowed:
            return Response({"cause": "该错因不适用于当前学科。"}, status=400)
        for field in (
            "cause", "knowledge_summary", "notes", "correct_answer",
            "similar_problem_types",
        ):
            if field in data:
                setattr(mistake, field, data[field])
        mistake.save(update_fields=(*data.keys(), "updated_at"))
        return Response(MistakeSerializer(mistake, context={"request": request}).data)


def mistake_check_in_summary(profile, subject, request):
    today = timezone.localdate()
    check_ins = profile.mistake_check_ins.filter(subject=subject)
    checked_dates = set(
        check_ins.filter(checked_on__gte=today - timedelta(days=365))
        .values_list("checked_on", flat=True)
    )
    checked_in_today = today in checked_dates
    cursor = today if checked_in_today else today - timedelta(days=1)
    streak = 0
    while cursor in checked_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return {
        "subject": subject,
        "checked_in_today": checked_in_today,
        "streak": streak,
        "check_ins": MistakeCheckInSerializer(
            check_ins[:14], many=True, context={"request": request}
        ).data,
    }


class MistakeCheckInView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        serializer = MistakeCheckInInputSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        subject = serializer.validated_data.get("subject") or profile.primary_subject
        return Response(mistake_check_in_summary(profile, subject, request))


class ReviewListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        reviews = profile.review_schedules.select_related(
            "mistake", "mistake__problem", "mistake__knowledge_point"
        ).prefetch_related("mistake__problem__attempts")
        if request.query_params.get("due", "1") != "0":
            reviews = reviews.filter(next_review_at__lte=timezone.now())
        subject = request.query_params.get("subject")
        if subject:
            reviews = reviews.filter(subject=subject)
        return Response(ReviewSerializer(reviews[:100], many=True, context={"request": request}).data)


class ReviewCompleteView(StudyAPIView):
    def post(self, request, organization_id, application_id, review_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        review = profile.review_schedules.select_related("mistake").filter(pk=review_id).first()
        if review is None:
            return Response({"detail": "复习任务不存在。"}, status=404)
        if not isinstance(request.data.get("is_correct"), bool):
            return Response({"is_correct": "请标记本次复习是否正确。"}, status=400)
        complete_review(review, request.data["is_correct"])
        return Response(ReviewSerializer(review, context={"request": request}).data)


class ReportListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        workspace = self.workspace(organization_id, application_id)
        if workspace is None:
            return Response({"detail": "应用尚未安装。"}, status=404)
        profile = self.own_profile(request, organization_id, application_id)
        if profile:
            reports = profile.weekly_reports.all()
        else:
            profile_ids = GuardianLink.objects.for_organization(organization_id).filter(
                guardian=request.user, is_active=True, profile__workspace=workspace
            ).values_list("profile_id", flat=True)
            reports = WeeklyReport.objects.for_organization(organization_id).filter(
                profile_id__in=profile_ids
            ).select_related("profile")
        if request.query_params.get("aggregate") == "1":
            return Response(_report_summary(reports[:52]))
        return Response(WeeklyReportSerializer(reports[:52], many=True).data)

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        subject = request.data.get("subject")
        if subject:
            enrollment = active_enrollment(profile, subject)
            if enrollment is None:
                return Response({"detail": "未启用该学科。"}, status=400)
            report = build_weekly_report(profile, enrollment)
            return Response(WeeklyReportSerializer(report).data, status=201)
        reports = [
            build_weekly_report(profile, enrollment)
            for enrollment in profile.enrollments.filter(is_active=True)
        ]
        return Response(_report_summary(reports), status=201)


class QuizListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        quizzes = profile.weekly_quizzes.all()
        subject = request.query_params.get("subject")
        if subject:
            quizzes = quizzes.filter(subject=subject)
        return Response(WeeklyQuizSerializer(quizzes[:24], many=True).data)

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        enrollment = active_enrollment(profile, request.data.get("subject", Subject.MATH))
        if enrollment is None:
            return Response({"detail": "未启用该学科。"}, status=400)
        try:
            quiz = build_weekly_quiz(profile, enrollment)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(WeeklyQuizSerializer(quiz).data, status=201)


class QuizSubmitView(StudyAPIView):
    def post(self, request, organization_id, application_id, quiz_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        quiz = profile.weekly_quizzes.filter(pk=quiz_id).first()
        if quiz is None:
            return Response({"detail": "周测不存在。"}, status=404)
        answers = request.data.get("answers")
        if not isinstance(answers, list):
            return Response({"answers": "答案必须是列表。"}, status=400)
        try:
            submit_weekly_quiz(quiz, answers)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(WeeklyQuizSerializer(quiz).data)


class AnswerCardListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        cards = profile.answer_cards.all()
        subject = request.query_params.get("subject")
        if subject:
            cards = cards.filter(subject=subject)
        return Response(AnswerCardSerializer(cards[:50], many=True).data)

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        serializer = AnswerCardCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = active_enrollment(profile, serializer.validated_data["subject"])
        if enrollment is None:
            return Response({"detail": "未启用该学科。"}, status=400)
        try:
            card = build_answer_card(
                profile,
                enrollment,
                curriculum_version=serializer.validated_data["curriculum_version"],
                knowledge_point_code=serializer.validated_data["knowledge_point_code"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except TeachingDataError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response(AnswerCardSerializer(card).data, status=201)


class AnswerCardSubmitView(StudyAPIView):
    def post(self, request, organization_id, application_id, card_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        card = profile.answer_cards.filter(pk=card_id).first()
        if card is None:
            return Response({"detail": "答题卡不存在。"}, status=404)
        if not isinstance(request.data.get("answers"), list):
            return Response({"answers": "答案必须是列表。"}, status=400)
        serializer = AnswerCardSubmitSerializer(
            data=request.data["answers"], many=True
        )
        serializer.is_valid(raise_exception=True)
        try:
            card = submit_answer_card(card, serializer.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AnswerCardSerializer(card).data)


class GuardianListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        return Response(GuardianLinkSerializer(profile.guardian_links.all(), many=True).data)

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        identifier = str(request.data.get("identifier") or "").strip()
        if not identifier:
            return Response({"identifier": "请输入家长用户名或邮箱。"}, status=400)
        User = get_user_model()
        organization_users = User.objects.filter(
            organization_memberships__organization_id=organization_id,
            organization_memberships__is_active=True,
        ).distinct()

        # Usernames are unique and therefore take precedence over email matches.
        # Email addresses are not unique in the current user model, so exclude the
        # student before selecting a guardian. Otherwise a shared family email can
        # resolve to the student first and incorrectly trigger the self-link guard.
        guardian = organization_users.filter(username=identifier).first()
        if guardian is None:
            guardian = organization_users.filter(
                email__iexact=identifier,
            ).exclude(pk=request.user.pk).order_by("pk").first()
        if guardian is None:
            if organization_users.filter(
                pk=request.user.pk,
            ).filter(Q(username=identifier) | Q(email__iexact=identifier)).exists():
                return Response({"identifier": "不能把自己设为家长。"}, status=400)
            return Response({"identifier": "未找到该组织中的账号。"}, status=404)
        if guardian == request.user:
            return Response({"identifier": "不能把自己设为家长。"}, status=400)
        link, created = GuardianLink.objects.update_or_create(
            organization=request.organization,
            profile=profile,
            guardian=guardian,
            defaults={"created_by": request.user, "is_active": True},
        )
        return Response(GuardianLinkSerializer(link).data, status=201 if created else 200)


class GuardianDetailView(StudyAPIView):
    def delete(self, request, organization_id, application_id, link_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        link = profile.guardian_links.filter(pk=link_id).first()
        if link is None:
            return Response({"detail": "家长关联不存在。"}, status=404)
        link.delete()
        return Response(status=204)


class ExportView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        return Response({
            "exported_at": timezone.now(),
            "profile": ProfileSerializer(profile, context={"request": request}).data,
            "tasks": StudyTaskSerializer(profile.tasks.all(), many=True).data,
            "problems": ProblemSerializer(
                profile.problems.prefetch_related("attempts"), many=True, context={"request": request}
            ).data,
            "mistakes": MistakeSerializer(
                profile.mistakes.select_related("problem", "review_schedule").prefetch_related("problem__attempts"),
                many=True,
                context={"request": request},
            ).data,
            "mistake_check_ins": MistakeCheckInSerializer(
                profile.mistake_check_ins.all(), many=True
            ).data,
            "reports": WeeklyReportSerializer(profile.weekly_reports.all(), many=True).data,
            "quizzes": WeeklyQuizSerializer(profile.weekly_quizzes.all(), many=True).data,
            "answer_cards": AnswerCardSerializer(profile.answer_cards.all(), many=True).data,
        })


class DataDeleteView(StudyAPIView):
    def delete(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        confirmation = str(
            request.data.get("confirmation")
            or request.query_params.get("confirmation")
            or ""
        )
        if confirmation != "删除我的学习数据":
            return Response({"confirmation": "请输入“删除我的学习数据”确认。"}, status=400)
        for problem in profile.problems.exclude(source_image=""):
            problem.source_image.delete(save=False)
        profile.delete()
        return Response(status=204)

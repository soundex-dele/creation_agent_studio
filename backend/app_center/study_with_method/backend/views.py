from __future__ import annotations

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
    AttemptInputSerializer,
    AttemptSerializer,
    GuardianLinkSerializer,
    ManualMistakeInputSerializer,
    MasterySerializer,
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
    build_weekly_report,
    build_weekly_quiz,
    complete_review,
    generate_week_plan,
    record_attempt,
    reschedule_overdue_tasks,
    resolve_curriculum_node,
    start_tutor_run,
    submit_weekly_quiz,
)
from .strategies import get_subject_strategy


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

        enrollment = active_enrollment(profile)
        if enrollment:
            reschedule_overdue_tasks(profile)
            generate_week_plan(profile, enrollment)
        today = timezone.localdate()
        tasks = profile.tasks.filter(scheduled_for=today)
        reviews = profile.review_schedules.filter(next_review_at__lte=timezone.now())
        latest_report = profile.weekly_reports.first()
        return Response({
            "mode": "student",
            "profile": ProfileSerializer(profile, context={"request": request}).data,
            "today": str(today),
            "tasks": StudyTaskSerializer(tasks, many=True).data,
            "due_reviews": ReviewSerializer(reviews[:5], many=True, context={"request": request}).data,
            "due_review_count": reviews.count(),
            "mistake_count": profile.mistakes.count(),
            "masteries": MasterySerializer(profile.masteries.order_by("score")[:5], many=True).data,
            "latest_report": WeeklyReportSerializer(latest_report).data if latest_report else None,
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
        with transaction.atomic():
            profile, _ = StudyProfile.objects.update_or_create(
                organization=request.organization,
                workspace=workspace,
                student=request.user,
                defaults={
                    "display_name": data.get("display_name", ""),
                    "region": data.get("region", ""),
                    "primary_subject": data["subject"],
                    "grade_stage": data["grade_stage"],
                    "daily_minutes": data["daily_minutes"],
                    "latest_score": data.get("latest_score"),
                    "target_score": data.get("target_score"),
                    "onboarding_completed": True,
                },
            )
            enrollment, _ = SubjectEnrollment.objects.update_or_create(
                organization=request.organization,
                profile=profile,
                subject=data["subject"],
                grade_stage=data["grade_stage"],
                defaults={
                    "curriculum_version": data["curriculum_version"],
                    "current_chapter": data["current_chapter"],
                    "weak_topics": data["weak_topics"],
                    "is_active": True,
                },
            )
            generate_week_plan(profile, enrollment)
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
        knowledge = resolve_curriculum_node(data["subject"], strategy.detect_topic(text)) if text else None
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
        problem.knowledge_point = resolve_curriculum_node(problem.subject, strategy.detect_topic(text))
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
        return Response(MistakeSerializer(mistakes[:100], many=True, context={"request": request}).data)

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
        return Response(WeeklyReportSerializer(reports[:52], many=True).data)

    def post(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        enrollment = active_enrollment(profile, request.data.get("subject", Subject.MATH))
        if enrollment is None:
            return Response({"detail": "未启用该学科。"}, status=400)
        report = build_weekly_report(profile, enrollment)
        return Response(WeeklyReportSerializer(report).data, status=201)


class QuizListView(StudyAPIView):
    def get(self, request, organization_id, application_id):
        profile, error = self.require_profile(request, organization_id, application_id)
        if error:
            return error
        return Response(WeeklyQuizSerializer(profile.weekly_quizzes.all()[:12], many=True).data)

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
            "reports": WeeklyReportSerializer(profile.weekly_reports.all(), many=True).data,
            "quizzes": WeeklyQuizSerializer(profile.weekly_quizzes.all(), many=True).data,
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

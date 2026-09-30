import hashlib
import json
from copy import deepcopy

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition, CommandNotAllowed
from .catalog import catalog, SCENES
from .models import PromptSession, PromptVersion, PromptTask
from .serializers import SessionInput, TaskInput, VersionInput, validate_answers

ACTIVE = {"queued", "running", "waiting_input", "waiting_children", "cancelling"}
INPUT_FIELDS = ("mode", "topic", "original", "objective", "scene", "language")


def task_data(task):
    if task is None:
        return None
    status, error = task.status, task.error
    if task.run and status in ACTIVE and task.run.status in {"failed", "cancelled", "succeeded"}:
        status = "failed" if task.run.status == "succeeded" else task.run.status
        error = error or "任务未完成，请检查模型配置或手动重试。"
    return {"id": str(task.pk), "kind": task.kind, "status": status, "error": error,
            "revision": task.revision, "result": task.result, "created_at": task.created_at}


def snapshot(session):
    return {**{key: getattr(session, key) for key in INPUT_FIELDS}, "detected_scene": session.detected_scene,
            "questions": deepcopy(session.questions), "answers": deepcopy(session.answers),
            "rounds": session.rounds, "analysis": deepcopy(session.analysis)}


def basis_matches(session, basis):
    return all(basis.get(key) == getattr(session, key) for key in (*INPUT_FIELDS, "answers"))


def version_data(version):
    if version is None:
        return None
    return {"id": str(version.pk), "source": version.source, "created_at": version.created_at,
            **{k: getattr(version, k) for k in ("standard", "concise", "assumptions", "health", "changes", "constraints", "health_stale", "basis")}}


def session_data(session, detail=True):
    result = {"id": str(session.pk), "title": session.title, "mode": session.mode,
              "scene": session.scene, "detected_scene": session.detected_scene,
              "favorite": session.favorite, "revision": session.revision,
              "results_stale": session.results_stale, "created_at": session.created_at, "updated_at": session.updated_at}
    if detail:
        result.update(snapshot(session))
        result["latest_version"] = version_data(session.versions.first())
        result["latest_task"] = task_data(session.tasks.select_related("run").first())
    return result


class Pages(PageNumberPagination):
    page_size = 20


class Access(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return get_object_or_404(accessible_resources(
            Application.objects.for_organization(self.kwargs["organization_id"]).filter(
                is_active=True, slug="prompt-master", kind=Application.Kind.CUSTOM),
            self.request.user, operation="run"), pk=self.kwargs["application_id"])

    def sessions(self):
        application = self.application()
        return PromptSession.objects.for_organization(self.kwargs["organization_id"]).filter(
            application=application, owner=self.request.user, deleted_at__isnull=True)

    def session(self, lock=False):
        query = self.sessions()
        if lock:
            query = query.select_for_update()
        return get_object_or_404(query, pk=self.kwargs["session_id"])

    def conflict(self):
        return Response({"detail": "内容已在其他页面更新，请重新加载后再保存。"}, status=409)


class CatalogView(Access):
    def get(self, request, **kwargs):
        self.application()
        return Response(catalog())


def require_input(values):
    key = "original" if values["mode"] == "optimize" else "topic"
    if not values[key].strip():
        raise serializers.ValidationError({key: "请输入已有提示词。" if key == "original" else "请输入主题或任务。"})


class SessionsView(Access):
    def get(self, request, **kwargs):
        query = self.sessions()
        search = request.query_params.get("search", "")[:200]
        if search:
            query = query.filter(title__icontains=search)
        scene = request.query_params.get("scene")
        if scene in SCENES:
            from django.db.models import Q
            query = query.filter(Q(scene=scene) | Q(scene="auto", detected_scene=scene))
        if request.query_params.get("favorite") == "1":
            query = query.filter(favorite=True)
        paginator = Pages()
        rows = paginator.paginate_queryset(query, request)
        return paginator.get_paginated_response([session_data(row, False) for row in rows])

    def post(self, request, **kwargs):
        application = self.application()
        validator = SessionInput(data=request.data)
        validator.is_valid(raise_exception=True)
        values = dict(validator.validated_data)
        require_input(values)
        values.pop("revision", None)
        values.pop("answers", None)
        values.setdefault("title", (values["topic"] or values["original"])[:80])
        session = PromptSession.objects.create(organization_id=kwargs["organization_id"],
                                               application=application, owner=request.user, **values)
        return Response(session_data(session), status=201)


class SessionView(Access):
    def get(self, request, **kwargs):
        return Response(session_data(self.session()))

    @transaction.atomic
    def patch(self, request, **kwargs):
        session = self.session(lock=True)
        validator = SessionInput(data=request.data, partial=True)
        validator.is_valid(raise_exception=True)
        values = dict(validator.validated_data)
        if values.pop("revision", None) != session.revision:
            return self.conflict()
        combined = {**snapshot(session), **values}
        require_input(combined)
        changed_input = any(key in values and values[key] != getattr(session, key) for key in INPUT_FIELDS)
        if changed_input:
            session.questions = []
            session.answers = {}
            session.rounds = 0
            session.analysis = {}
            session.detected_scene = "general"
        if "answers" in values:
            values["answers"] = validate_answers(session.questions, values["answers"])
        if changed_input or ("answers" in values and values["answers"] != session.answers):
            session.results_stale = session.versions.exists()
        for key, value in values.items():
            setattr(session, key, value)
        session.revision += 1
        session.save()
        return Response(session_data(session))

    @transaction.atomic
    def delete(self, request, **kwargs):
        session = self.session(lock=True)
        if request.query_params.get("revision") != str(session.revision):
            return self.conflict()
        for task in session.tasks.select_related("run").filter(status__in=ACTIVE):
            cancel_task(task, request.user)
        session.deleted_at = timezone.now()
        session.save(update_fields=["deleted_at"])
        return Response(status=204)


class CopyView(Access):
    def post(self, request, **kwargs):
        source = self.session()
        copied = PromptSession.objects.create(organization_id=source.organization_id, application=source.application,
                                               owner=request.user, title=f"{source.title[:190]} · 副本",
                                               **{key: getattr(source, key) for key in INPUT_FIELDS})
        return Response(session_data(copied), status=201)


class VersionsView(Access):
    def get(self, request, **kwargs):
        paginator = Pages()
        rows = paginator.paginate_queryset(self.session().versions.all(), request)
        return paginator.get_paginated_response([version_data(row) for row in rows])

    @transaction.atomic
    def post(self, request, **kwargs):
        session = self.session(lock=True)
        validator = VersionInput(data=request.data)
        validator.is_valid(raise_exception=True)
        values = validator.validated_data
        if values["revision"] != session.revision:
            return self.conflict()
        parent = get_object_or_404(session.versions, pk=values["version_id"])
        PromptVersion.objects.create(organization_id=session.organization_id, session=session,
                                     source="manual", standard=values["standard"], concise=values["concise"],
                                     assumptions=parent.assumptions, health=parent.health, health_stale=True,
                                     changes=["手动编辑，体检待更新。"], basis=parent.basis)
        session.results_stale = not basis_matches(session, parent.basis)
        session.revision += 1
        session.save()
        return Response(session_data(session), status=201)


class TasksView(Access):
    @transaction.atomic
    def post(self, request, **kwargs):
        session = self.session(lock=True)
        validator = TaskInput(data=request.data)
        validator.is_valid(raise_exception=True)
        values = dict(validator.validated_data)
        key = values.pop("request_key")
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
        existing = session.tasks.filter(request_key=key).select_related("run").first()
        if existing:
            if existing.request_hash != digest:
                return Response({"detail": "同一请求键不能用于不同内容。"}, status=409)
            return Response(task_data(existing))
        if session.revision != values["revision"]:
            return self.conflict()
        if any(task_data(t)["status"] in ACTIVE for t in session.tasks.filter(status__in=ACTIVE).select_related("run")):
            return Response({"detail": "当前还有任务运行，请等待或取消。"}, status=409)
        if values["kind"] == "analyze" and session.rounds >= 2:
            raise serializers.ValidationError("已完成两轮提问，请生成结果或修改需求重新开始。")
        if values["kind"] in {"generate", "optimize"} and not session.rounds:
            raise serializers.ValidationError("请先分析需求。")
        if values["kind"] == "generate" and session.mode != "generate":
            raise serializers.ValidationError("优化会话应使用优化操作。")
        context = snapshot(session)
        context["instruction"] = values["instruction"]
        if values.get("version_id"):
            parent = get_object_or_404(session.versions, pk=values["version_id"])
            context["version"] = {key: value for key, value in version_data(parent).items() if key != "created_at"}
        if values["kind"] == "check" and "version" not in context:
            raise serializers.ValidationError("请选择要体检的版本。")
        task = PromptTask.objects.create(organization_id=session.organization_id, session=session,
                                         kind=values["kind"], revision=session.revision, snapshot=context,
                                         request_key=key, request_hash=digest)
        try:
            run, _ = start_application_run(organization_id=session.organization_id, application_id=session.application_id,
                                           actor=request.user, input_data={"task_id": str(task.pk)},
                                           priority=0, idempotency_key=f"prompt-master:{task.pk}")
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            transaction.set_rollback(True)
            return Response({"detail": str(exc)}, status=409)
        task.run = run
        task.save(update_fields=["run"])
        return Response(task_data(task), status=202)


class TaskView(Access):
    def get(self, request, task_id, **kwargs):
        return Response(task_data(get_object_or_404(self.session().tasks.select_related("run"), pk=task_id)))


def cancel_task(task, actor):
    if task_data(task)["status"] not in ACTIVE:
        return
    task.cancel_requested = True
    task.status = "cancelled"
    task.save(update_fields=["cancel_requested", "status"])
    if task.run and task.run.status in ACTIVE:
        try:
            submit_run_command(run_id=task.run_id, organization_id=task.organization_id, actor=actor,
                               command_type="cancel", idempotency_key=f"prompt-master-cancel:{task.pk}")
        except CommandNotAllowed:
            pass


class CancelView(Access):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        session = self.session(lock=True)
        task = get_object_or_404(session.tasks.select_for_update(of=("self",)).select_related("run"), pk=task_id)
        cancel_task(task, request.user)
        return Response(task_data(task))

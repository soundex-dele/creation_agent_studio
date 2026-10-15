import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.enterprise.models import Membership
from apps.knowledge.models import KnowledgeBase
from apps.knowledge.services import reindex_document
from core.resource_access import accessible_resources
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from modules.execution.infrastructure.artifacts import get_artifact_storage, ArtifactObjectUnavailable
from modules.tenancy.permissions import HasPathOrganizationRole
from .access import application_for, project_for
from .content import markdown
from .models import ResearchProject, ResearchResult
from .serializers import (ProjectSerializer, SourceInput, GenerateInput, ExportInput,
                          SourceOutput, ResultOutput, CitationOutput, ProjectPage, ResultPage)
from .services import ingest, fingerprint, request_key, source_limits, cancel, delete_project, cleanup_project, export_result, public_origin

IDEMPOTENCY_HEADER = openapi.Parameter("Idempotency-Key", openapi.IN_HEADER, type=openapi.TYPE_STRING, required=True,
                                      description="重试使用同一键；新生成或新副本使用新键，最多 160 字符。")


def source_data(source):
    doc = source.document
    return {"id": str(source.id), "title": doc.title, "origin": source.origin, "status": doc.status,
            "filename": doc.original_filename, "byte_size": doc.byte_size, "error": doc.error,
            "error_code": doc.error_code, "metadata": doc.metadata, "indexing_run_id": str(doc.indexing_run_id or ""),
            "removed": source.removed}


def result_data(result, *, detail=False):
    run = result.run
    progress = run.events.filter(type="progress.updated").order_by("-sequence").first() if run else None
    data = {"id": str(result.id), "kind": result.kind, "instruction": result.instruction,
            "objective": result.objective, "source_ids": [s["source_id"] for s in result.source_snapshot],
            "created_at": result.created_at, "run_id": str(run.id) if run else None,
            "status": run.status if run else "failed", "error": run.error_message if run else "任务记录已删除。",
            "progress": progress.payload if progress else None}
    if detail:
        data["output"] = run.output_summary if run and run.status == "succeeded" else None
    return data


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def project(self, **options):
        return project_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"],
                           self.kwargs["project_id"], **options)

    def page(self, qs, serialize):
        pager = PageNumberPagination()
        pager.page_size = 20
        return pager.get_paginated_response([serialize(item) for item in pager.paginate_queryset(qs, self.request)])


class ProjectsView(BaseView):
    @swagger_auto_schema(responses={200: ProjectPage})
    def get(self, request, **kwargs):
        app = self.application()
        qs = ResearchProject.objects.filter(application=app, organization=app.organization, owner=request.user, deleted_at=None)
        if request.query_params.get("search"):
            qs = qs.filter(title__icontains=request.query_params["search"][:200])
        return self.page(qs, lambda p: ProjectSerializer(p).data)

    @swagger_auto_schema(request_body=ProjectSerializer, responses={201: ProjectSerializer})
    @transaction.atomic
    def post(self, request, **kwargs):
        app = self.application()
        serializer = ProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pk = uuid.uuid4()
        kb = KnowledgeBase.objects.create(organization=app.organization, scope="research", name=f"research:{pk}",
            embedding_provider=getattr(settings, "RESEARCH_EMBEDDING_PROVIDER", ""),
            embedding_model=getattr(settings, "RESEARCH_EMBEDDING_MODEL", ""))
        project = serializer.save(id=pk, application=app, organization=app.organization, owner=request.user, knowledge_base=kb)
        return Response(ProjectSerializer(project).data, status=201)


class ProjectView(BaseView):
    @swagger_auto_schema(responses={200: ProjectSerializer})
    def get(self, request, **kwargs):
        return Response({**ProjectSerializer(self.project()).data, "limits": source_limits()})

    @swagger_auto_schema(request_body=ProjectSerializer, responses={200: ProjectSerializer})
    @transaction.atomic
    def patch(self, request, **kwargs):
        serializer = ProjectSerializer(self.project(lock=True), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, **kwargs):
        with transaction.atomic():
            project = self.project(lock=True, deleted=True)
            delete_project(project)
        try:
            cleanup_project(project)
        except Exception:
            return Response({"detail": "项目已停用，文件清理待重试。"}, status=503)
        return Response(status=204)


class SourcesView(BaseView):
    @swagger_auto_schema(responses={200: SourceOutput(many=True)})
    def get(self, request, **kwargs):
        project = self.project()
        return Response([source_data(s) for s in project.sources.filter(removed=False).select_related("document")])

    @swagger_auto_schema(request_body=SourceInput, responses={200: SourceOutput, 202: SourceOutput})
    @transaction.atomic
    def post(self, request, **kwargs):
        project = self.project(lock=True)
        serializer = SourceInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        source, reused = ingest(project, request.user, serializer.validated_data)
        return Response({**source_data(source), "reused": reused}, status=200 if reused else 202)


class SourceView(BaseView):
    @transaction.atomic
    def delete(self, request, source_id, **kwargs):
        source = get_object_or_404(self.project(lock=True).sources, pk=source_id)
        source.removed = True
        source.save(update_fields=["removed"])
        return Response(status=204)


class SourceRetryView(BaseView):
    @swagger_auto_schema(responses={202: SourceOutput})
    @transaction.atomic
    def post(self, request, source_id, **kwargs):
        source = get_object_or_404(self.project(lock=True).sources.select_related("document"), pk=source_id, removed=False)
        if source.document.status != "failed":
            raise ValidationError("仅失败的资料可以重试索引。")
        reindex_document(source.document, request.user)
        source.document.refresh_from_db()
        return Response(source_data(source), status=202)


class SourceContentView(BaseView):
    def get(self, request, source_id, **kwargs):
        source = get_object_or_404(self.project().sources.select_related("document"), pk=source_id)
        try:
            handle = get_artifact_storage().open(source.document.source_object_key)
        except ArtifactObjectUnavailable:
            raise Http404("资料原文件不可用。") from None
        response = FileResponse(handle, as_attachment=True, filename=source.document.original_filename,
                                content_type=source.document.mime_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ResultsView(BaseView):
    @swagger_auto_schema(responses={200: ResultPage})
    def get(self, request, **kwargs):
        return self.page(self.project().results.select_related("run"), result_data)

    @swagger_auto_schema(request_body=GenerateInput, responses={200: ResultOutput, 202: ResultOutput}, manual_parameters=[IDEMPOTENCY_HEADER])
    @transaction.atomic
    def post(self, request, **kwargs):
        project = self.project(lock=True)
        serializer = GenerateInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        values["source_ids"] = sorted(set(str(pk) for pk in values["source_ids"]))
        key, digest = request_key(request), fingerprint(values)
        existing = project.results.filter(request_key=key).select_related("run").first()
        if existing:
            if existing.request_hash != digest:
                return Response({"detail": "同一请求键已用于其他生成要求。"}, status=409)
            return Response(result_data(existing, detail=True))
        if not project.objective.strip():
            raise ValidationError("请先填写研究目标。")
        sources = list(project.sources.filter(pk__in=values["source_ids"], removed=False,
                       document__status="ready", document__is_deleted=False).select_related("document"))
        if len(sources) != len(values["source_ids"]):
            raise ValidationError("所选资料尚未就绪或已移出项目。")
        result = ResearchResult.objects.create(project=project, kind=values["kind"], instruction=values["instruction"],
            objective=project.objective, request_key=key, request_hash=digest,
            source_snapshot=[{"source_id": str(s.id), "document_id": s.document_id, "revision": s.document.active_revision} for s in sources])
        try:
            run, _ = start_application_run(organization_id=project.organization_id, application_id=project.application_id,
                actor=request.user, input_data={"research_project_id": str(project.id), "result_id": str(result.id)}, priority=0,
                idempotency_key=f"research:{result.id}")
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            transaction.set_rollback(True)
            return Response({"detail": str(exc)}, status=409)
        result.run = run
        result.save(update_fields=["run"])
        return Response(result_data(result, detail=True), status=202)


class ResultView(BaseView):
    @swagger_auto_schema(responses={200: ResultOutput})
    def get(self, request, result_id, **kwargs):
        result = get_object_or_404(self.project().results.select_related("run"), pk=result_id)
        return Response(result_data(result, detail=True))


class ResultCancelView(BaseView):
    @swagger_auto_schema(responses={200: ResultOutput})
    def post(self, request, result_id, **kwargs):
        result = get_object_or_404(self.project().results.select_related("run"), pk=result_id)
        cancel(result.run, request.user, "user_cancelled")
        result.run.refresh_from_db()
        return Response(result_data(result))


class CitationView(BaseView):
    @swagger_auto_schema(responses={200: CitationOutput})
    def get(self, request, result_id, citation_id, **kwargs):
        result = get_object_or_404(self.project().results.select_related("run"), pk=result_id, run__status="succeeded")
        citation = next((c for c in result.run.output_summary.get("citations", []) if c["id"] == citation_id), None)
        if citation is None:
            raise Http404()
        source = get_object_or_404(result.project.sources.select_related("document"), pk=citation["source_id"])
        chunk = get_object_or_404(source.document.chunks, pk=citation["chunk_id"], revision=citation["revision"])
        return Response({**citation, "context": chunk.content, "origin": source.origin, "filename": source.document.original_filename})


class ResultDownloadView(BaseView):
    def get(self, request, result_id, **kwargs):
        result = get_object_or_404(self.project().results.select_related("run"), pk=result_id, run__status="succeeded")
        response = HttpResponse(markdown(result.run.output_summary, public_origin(request), result.project, result),
                                content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, result.run.output_summary["title"][:200] + ".md")
        response["Cache-Control"] = "private, no-store"
        return response


class ResultExportView(BaseView):
    @swagger_auto_schema(request_body=ExportInput, manual_parameters=[IDEMPOTENCY_HEADER])
    @transaction.atomic
    def post(self, request, result_id, **kwargs):
        result = get_object_or_404(self.project(lock=True).results.select_related("run", "project"), pk=result_id, run__status="succeeded")
        serializer = ExportInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(export_result(result, request.user, serializer.validated_data, request_key(request), public_origin(request)))


class IntegrationsView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        apps = accessible_resources(Application.objects.for_organization(app.organization_id).filter(
            slug__in=["documents", "my-drive"], is_active=True, kind="custom"), request.user, operation="run")
        return Response({"applications": [{"id": a.id, "name": a.name, "target": "document" if a.slug == "documents" else "drive"} for a in apps],
                         "limits": source_limits()})


class ImportsView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        try:
            target_id = int(request.query_params.get("application_id", ""))
        except ValueError:
            raise ValidationError("请选择来源应用。") from None
        search = request.query_params.get("search", "")[:200]
        if request.query_params.get("target") == "document":
            from app_center.documents.backend.access import visible_documents
            qs = visible_documents(request.user, app.organization_id, target_id).filter(title__icontains=search).order_by("-updated_at", "pk")
            return self.page(qs, lambda d: {"id": str(d.id), "title": d.title, "kind": "file", "version": d.version})
        if request.query_params.get("target") != "drive":
            raise ValidationError("未知来源类型。")
        from app_center.my_drive.backend.access import application_for as drive_app, space_for
        from app_center.my_drive.backend.services import entries, folder_for
        target = drive_app(request.user, app.organization_id, target_id)
        qs = entries(space_for(request.user, app.organization_id), target).filter(trash_batch=None, purge_pending=False)
        if search:
            qs = qs.filter(name__icontains=search)
        else:
            parent = request.query_params.get("parent") or None
            if parent:
                try:
                    parent = uuid.UUID(parent)
                except ValueError:
                    raise ValidationError("文件夹编号无效。") from None
                folder_for(qs, parent)
            qs = qs.filter(parent_id=parent)
        return self.page(qs.order_by("kind", "name", "id"), lambda d: {"id": str(d.id), "title": d.name, "kind": d.kind, "byte_size": d.size})

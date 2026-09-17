from django.db.models import Count, Q
from django.db.models import Sum
from django.http import FileResponse, HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

from apps.enterprise.models import Membership
from apps.enterprise.models import QuotaPolicy
from apps.enterprise.services import record_usage
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import IdempotencyKeyReused
from modules.execution.application.commands import submit_run_command
from modules.execution.models import Run, RunCommand
from modules.execution.infrastructure.artifacts import (
    ArtifactObjectUnavailable, delete_artifact_object, get_artifact_storage,
)
from modules.tenancy.permissions import HasPathOrganizationRole, ROLE_LEVEL

from .models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from .index_backend import delete_document_index
from .providers import ProviderUnavailable, embed_texts
from .retrieval import search
from .serializers import (
    KnowledgeAnswerRunInputSerializer,
    KnowledgeAnswerAcceptedSerializer,
    KnowledgeBaseDetailSerializer,
    KnowledgeBaseSummarySerializer,
    KnowledgeDocumentSerializer,
    KnowledgeDocumentCreateSerializer,
    KnowledgeIndexAcceptedSerializer,
    KnowledgeSearchRequestSerializer,
    KnowledgeSearchResponseSerializer,
)
from .services import (
    create_document, reindex_document, replay_answer_run, start_answer_run,
)


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "docx", "md", "markdown", "txt"}


def _role_at_least(request, role):
    if request.user.is_superuser:
        return True
    membership = getattr(request, "organization_membership", None)
    return membership and ROLE_LEVEL.get(membership.role, 0) >= ROLE_LEVEL[role]


def _knowledge_base(organization_id, pk):
    return KnowledgeBase.objects.for_organization(organization_id).filter(pk=pk).first()


def _document(organization_id, pk, document_id):
    return KnowledgeDocument.objects.for_organization(organization_id).filter(
        pk=document_id, knowledge_base_id=pk, is_deleted=False,
    ).select_related("knowledge_base").first()


def _cancel_indexing_run(document, organization_id, actor):
    if not document.indexing_run_id or document.indexing_run.status in {
        Run.Status.SUCCEEDED, Run.Status.FAILED, Run.Status.CANCELLED,
    }:
        return
    try:
        submit_run_command(
            run_id=document.indexing_run_id,
            organization_id=organization_id,
            actor=actor,
            command_type=RunCommand.Type.CANCEL,
            idempotency_key=f"knowledge-delete:{document.id}",
            payload={"reason": "knowledge_document_deleted"},
        )
    except Exception:
        pass


def _embed_query(base, query):
    vectors = embed_texts(
        base.organization,
        base.embedding_provider,
        base.embedding_model,
        [query],
    )
    return (
        vectors[0],
        getattr(vectors, "usage", {}),
        getattr(vectors, "model", "") or base.embedding_model,
    )


def _compatible_embedding_base(bases):
    configurations = list(
        bases.exclude(embedding_model="")
        .values_list("embedding_provider", "embedding_model")
        .distinct()[:2]
    )
    if len(configurations) != 1:
        return None
    provider, model = configurations[0]
    return bases.filter(
        embedding_provider=provider, embedding_model=model,
    ).order_by("id").first()


class KnowledgeBaseListView(APIView):
    permission_classes = [HasPathOrganizationRole]

    @swagger_auto_schema(responses={200: KnowledgeBaseSummarySerializer(many=True)})
    def get(self, request, organization_id):
        queryset = KnowledgeBase.objects.for_organization(organization_id).annotate(
            document_count=Count("documents", filter=Q(documents__is_deleted=False)),
        ).order_by("name")
        return Response(KnowledgeBaseSummarySerializer(queryset, many=True).data)

    @swagger_auto_schema(
        request_body=KnowledgeBaseDetailSerializer,
        responses={201: KnowledgeBaseDetailSerializer},
    )
    def post(self, request, organization_id):
        serializer = KnowledgeBaseDetailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        knowledge_base = serializer.save(organization=request.organization)
        knowledge_base.document_count = 0
        return Response(
            KnowledgeBaseDetailSerializer(knowledge_base).data,
            status=status.HTTP_201_CREATED,
        )


class KnowledgeBaseDetailView(APIView):
    permission_classes = [HasPathOrganizationRole]

    @swagger_auto_schema(responses={200: KnowledgeBaseDetailSerializer})
    def get(self, request, organization_id, pk):
        value = _knowledge_base(organization_id, pk)
        if value is None:
            return Response({"detail": "Not found."}, status=404)
        value.document_count = value.documents.filter(is_deleted=False).count()
        return Response(KnowledgeBaseDetailSerializer(value).data)

    @swagger_auto_schema(
        request_body=KnowledgeBaseDetailSerializer,
        responses={200: KnowledgeBaseDetailSerializer},
    )
    def patch(self, request, organization_id, pk):
        value = _knowledge_base(organization_id, pk)
        if value is None:
            return Response({"detail": "Not found."}, status=404)
        model_fields = {"embedding_provider", "embedding_model", "answer_provider", "answer_model"}
        if model_fields.intersection(request.data) and not _role_at_least(request, Membership.Role.ADMIN):
            return Response({"detail": "Administrator role is required to change model settings."}, status=403)
        serializer = KnowledgeBaseDetailSerializer(value, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        value = serializer.save()
        value.document_count = value.documents.filter(is_deleted=False).count()
        return Response(KnowledgeBaseDetailSerializer(value).data)

    def delete(self, request, organization_id, pk):
        if not _role_at_least(request, Membership.Role.ADMIN):
            return Response({"detail": "Administrator role is required."}, status=403)
        value = _knowledge_base(organization_id, pk)
        if value is None:
            return Response(status=204)
        if value.is_active:
            value.is_active = False
            value.save(update_fields=["is_active", "updated_at"])
        documents = list(value.documents.select_related("indexing_run"))
        object_keys = [item.source_object_key for item in documents if item.source_object_key]
        for document in documents:
            _cancel_indexing_run(document, organization_id, request.user)
            try:
                delete_document_index(document.id)
            except Exception as exc:
                return Response({
                    "detail": "Index cleanup failed; retry deletion.",
                    "error": str(exc)[:500],
                }, status=503)
        try:
            for object_key in object_keys:
                delete_artifact_object(object_key)
        except Exception as exc:
            return Response({
                "detail": "Source cleanup failed; retry deletion.",
                "error": str(exc)[:500],
            }, status=503)
        value.delete()
        return Response(status=204)


class KnowledgeDocumentListView(APIView):
    permission_classes = [HasPathOrganizationRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(responses={200: KnowledgeDocumentSerializer(many=True)})
    def get(self, request, organization_id, pk):
        knowledge_base = _knowledge_base(organization_id, pk)
        if knowledge_base is None:
            return Response({"detail": "Not found."}, status=404)
        documents = knowledge_base.documents.filter(is_deleted=False).order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            documents = documents.filter(status=status_filter)
        return Response(KnowledgeDocumentSerializer(documents, many=True).data)

    @swagger_auto_schema(
        request_body=KnowledgeDocumentCreateSerializer,
        responses={202: KnowledgeIndexAcceptedSerializer},
    )
    def post(self, request, organization_id, pk):
        knowledge_base = _knowledge_base(organization_id, pk)
        if knowledge_base is None:
            return Response({"detail": "Not found."}, status=404)
        uploaded = request.FILES.get("file")
        text = request.data.get("text")
        if bool(uploaded) == bool(text):
            return Response({"detail": "Provide exactly one of file or text."}, status=400)
        if uploaded:
            if uploaded.size > MAX_FILE_BYTES:
                return Response({"file": "File exceeds the 50 MiB limit."}, status=413)
            filename = uploaded.name
            extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if extension not in ALLOWED_EXTENSIONS:
                return Response({"file": "Only PDF, DOCX, Markdown and TXT are supported."}, status=415)
            content = uploaded.read()
            mime_type = uploaded.content_type or "application/octet-stream"
            source_type = KnowledgeDocument.SourceType.UPLOAD
            title = str(request.data.get("title") or filename).strip()
        else:
            content = str(text).encode("utf-8")
            if len(content) > MAX_TEXT_BYTES:
                return Response({"text": "Text exceeds the 2 MiB limit."}, status=413)
            filename = "pasted-text.txt"
            mime_type = "text/plain; charset=utf-8"
            source_type = KnowledgeDocument.SourceType.TEXT
            title = str(request.data.get("title") or "粘贴文本").strip()
        if not content or not title:
            return Response({"detail": "Title and non-empty content are required."}, status=400)
        quota, _ = QuotaPolicy.objects.get_or_create(organization=request.organization)
        stored = KnowledgeDocument.objects.for_organization(organization_id).filter(
            is_deleted=False).aggregate(total=Sum("byte_size"))["total"] or 0
        if quota.hard_limit and stored + len(content) > quota.storage_bytes_limit:
            return Response({"detail": "Organization storage quota exceeded."}, status=429)
        try:
            document, run = create_document(
                knowledge_base=knowledge_base,
                actor=request.user,
                title=title,
                source_type=source_type,
                filename=filename,
                mime_type=mime_type,
                content=content,
            )
        except ValueError as exc:
            if str(exc).startswith("duplicate:"):
                return Response({
                    "detail": "The same content already exists in this knowledge base.",
                    "document_id": int(str(exc).split(":", 1)[1]),
                }, status=409)
            raise
        return Response({
            "document": KnowledgeDocumentSerializer(document).data,
            "run": RunSerializer(run).data,
            "run_url": f"/api/v1/organizations/{organization_id}/runs/{run.id}",
            "stream_url": f"/api/v1/organizations/{organization_id}/runs/{run.id}/stream",
        }, status=202)


class KnowledgeDocumentDetailView(APIView):
    permission_classes = [HasPathOrganizationRole]

    @swagger_auto_schema(responses={200: KnowledgeDocumentSerializer})
    def get(self, request, organization_id, pk, document_id):
        value = _document(organization_id, pk, document_id)
        return Response(
            KnowledgeDocumentSerializer(value).data if value else {"detail": "Not found."},
            status=200 if value else 404,
        )

    def delete(self, request, organization_id, pk, document_id):
        if not _role_at_least(request, Membership.Role.ADMIN):
            return Response({"detail": "Administrator role is required."}, status=403)
        value = KnowledgeDocument.objects.for_organization(organization_id).filter(
            pk=document_id, knowledge_base_id=pk,
        ).select_related("knowledge_base", "indexing_run").first()
        if value is None:
            return Response(status=204)
        if not value.is_deleted:
            value.is_deleted = True
            value.save(update_fields=["is_deleted", "updated_at"])
        _cancel_indexing_run(value, organization_id, request.user)
        KnowledgeChunk.objects.filter(document=value).delete()
        try:
            delete_document_index(value.id)
        except Exception as exc:
            return Response({
                "detail": "Index cleanup failed; retry deletion.",
                "error": str(exc)[:500],
            }, status=503)
        if value.source_object_key:
            try:
                delete_artifact_object(value.source_object_key)
            except Exception as exc:
                value.metadata = {
                    **value.metadata, "cleanup_error": str(exc)[:500],
                }
                value.save(update_fields=["metadata", "updated_at"])
                return Response({
                    "detail": "Source cleanup failed; retry deletion.",
                }, status=503)
            value.source_object_key = ""
            value.metadata = {
                key: item for key, item in value.metadata.items()
                if key != "cleanup_error"
            }
            value.save(update_fields=["source_object_key", "metadata", "updated_at"])
        return Response(status=204)


class KnowledgeDocumentReindexView(APIView):
    permission_classes = [HasPathOrganizationRole]

    @swagger_auto_schema(responses={202: KnowledgeIndexAcceptedSerializer})
    def post(self, request, organization_id, pk, document_id):
        value = _document(organization_id, pk, document_id)
        if value is None:
            return Response({"detail": "Not found."}, status=404)
        run = reindex_document(value, request.user)
        value.refresh_from_db()
        return Response({
            "document": KnowledgeDocumentSerializer(value).data,
            "run": RunSerializer(run).data,
            "run_url": f"/api/v1/organizations/{organization_id}/runs/{run.id}",
            "stream_url": f"/api/v1/organizations/{organization_id}/runs/{run.id}/stream",
        }, status=202)


class KnowledgeDocumentContentView(APIView):
    permission_classes = [HasPathOrganizationRole]

    def get(self, request, organization_id, pk, document_id):
        value = _document(organization_id, pk, document_id)
        if value is None:
            return Response({"detail": "Not found."}, status=404)
        if not value.source_object_key and value.content:
            response = HttpResponse(value.content, content_type="text/plain; charset=utf-8")
            response["Content-Disposition"] = content_disposition_header(
                False, value.original_filename or "document.txt")
            return response
        if not value.source_object_key:
            return Response({"detail": "The source object is unavailable."}, status=404)
        try:
            handle = get_artifact_storage().open(value.source_object_key)
        except ArtifactObjectUnavailable:
            return Response({"detail": "The source object is unavailable."}, status=404)
        response = FileResponse(handle, content_type=value.mime_type or "application/octet-stream")
        response["Content-Disposition"] = content_disposition_header(
            False, value.original_filename or "document")
        return response


class KnowledgeSearchView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    @swagger_auto_schema(
        request_body=KnowledgeSearchRequestSerializer,
        responses={200: KnowledgeSearchResponseSerializer},
    )
    def post(self, request, organization_id):
        serializer = KnowledgeSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        bases = KnowledgeBase.objects.for_organization(organization_id).filter(is_active=True)
        if values["knowledge_base_ids"]:
            bases = bases.filter(id__in=values["knowledge_base_ids"])
        base_ids = list(bases.values_list("id", flat=True))
        if values["knowledge_base_ids"] and len(base_ids) != len(set(values["knowledge_base_ids"])):
            return Response({"detail": "One or more knowledge bases are unavailable."}, status=404)
        query_embedding = None
        embedding_usage = {}
        embedding_model = ""
        embedding_provider = ""
        configured = _compatible_embedding_base(bases)
        if configured:
            try:
                query_embedding, embedding_usage, embedding_model = _embed_query(
                    configured, values["query"])
                embedding_provider = configured.embedding_provider
            except Exception:
                query_embedding = None
        mode, results = search(
            organization_id=organization_id,
            query=values["query"],
            knowledge_base_ids=base_ids,
            limit=values["limit"],
            query_embedding=query_embedding,
        )
        record_usage(
            organization=request.organization,
            user=request.user,
            resource_type="knowledge_search",
            resource_id=",".join(str(value) for value in base_ids),
            usage=embedding_usage,
            provider=embedding_provider,
            model=embedding_model,
            metadata={
                "retrieval_mode": mode,
                "result_count": len(results),
                "zero_hit": not results,
            },
        )
        return Response({"query": values["query"], "retrieval_mode": mode, "results": results})


class KnowledgeAnswerRunView(KnowledgeSearchView):
    @swagger_auto_schema(
        request_body=KnowledgeAnswerRunInputSerializer,
        manual_parameters=[openapi.Parameter(
            "Idempotency-Key", openapi.IN_HEADER,
            description="Unique key for replay-safe answer Run creation",
            type=openapi.TYPE_STRING, required=True,
        )],
        responses={202: KnowledgeAnswerAcceptedSerializer},
    )
    def post(self, request, organization_id):
        serializer = KnowledgeAnswerRunInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        key = str(request.headers.get("Idempotency-Key") or "").strip()
        if not key or len(key) > 160:
            return Response({"detail": "Idempotency-Key must contain between 1 and 160 characters."}, status=400)
        request_data = {
            "query": values["query"],
            "knowledge_base_ids": sorted(set(values["knowledge_base_ids"])),
            "limit": values["limit"],
        }
        try:
            replay = replay_answer_run(
                organization=request.organization,
                actor=request.user,
                request_data=request_data,
                idempotency_key=key,
            )
        except IdempotencyKeyReused as exc:
            return Response({"detail": str(exc)}, status=409)
        if replay is not None:
            response = Response({
                "run": RunSerializer(replay).data,
                "run_url": f"/api/v1/organizations/{organization_id}/runs/{replay.id}",
                "stream_url": f"/api/v1/organizations/{organization_id}/runs/{replay.id}/stream",
                "output": replay.output_summary or None,
            }, status=202)
            response["Idempotent-Replay"] = "true"
            return response
        bases = KnowledgeBase.objects.for_organization(organization_id).filter(is_active=True)
        if values["knowledge_base_ids"]:
            bases = bases.filter(id__in=values["knowledge_base_ids"])
        base_ids = list(bases.values_list("id", flat=True))
        if values["knowledge_base_ids"] and len(base_ids) != len(set(values["knowledge_base_ids"])):
            return Response({"detail": "One or more knowledge bases are unavailable."}, status=404)
        answer_base = bases.exclude(answer_model="").order_by("id").first()
        if answer_base is None:
            return Response({"detail": "Configure an answer model before using knowledge Q&A."}, status=409)
        providers = request.organization.providers.filter(is_active=True)
        if answer_base.answer_provider:
            providers = providers.filter(name=answer_base.answer_provider)
        if not providers.exists():
            return Response({"detail": "The configured answer provider is unavailable."}, status=409)
        query_embedding = None
        embedding_usage = {}
        embedding_model = ""
        embedding_provider = ""
        embedding_base = _compatible_embedding_base(bases)
        if embedding_base:
            try:
                query_embedding, embedding_usage, embedding_model = _embed_query(
                    embedding_base, values["query"])
                embedding_provider = embedding_base.embedding_provider
            except Exception:
                query_embedding = None
        mode, results = search(
            organization_id=organization_id,
            query=values["query"],
            knowledge_base_ids=base_ids,
            limit=values["limit"],
            query_embedding=query_embedding,
        )
        record_usage(
            organization=request.organization,
            user=request.user,
            resource_type="knowledge_answer_retrieval",
            resource_id=",".join(str(value) for value in base_ids),
            usage=embedding_usage,
            provider=embedding_provider,
            model=embedding_model,
            metadata={
                "retrieval_mode": mode,
                "result_count": len(results),
                "zero_hit": not results,
            },
        )
        try:
            run, replayed = start_answer_run(
                organization=request.organization,
                actor=request.user,
                query=values["query"],
                results=results,
                retrieval_mode=mode,
                answer_provider=answer_base.answer_provider,
                answer_model=answer_base.answer_model,
                idempotency_key=key,
                request_data=request_data,
            )
        except IdempotencyKeyReused as exc:
            return Response({"detail": str(exc)}, status=409)
        response = Response({
            "run": RunSerializer(run).data,
            "run_url": f"/api/v1/organizations/{organization_id}/runs/{run.id}",
            "stream_url": f"/api/v1/organizations/{organization_id}/runs/{run.id}/stream",
            "output": run.output_summary or None,
        }, status=202)
        if replayed:
            response["Idempotent-Replay"] = "true"
        return response

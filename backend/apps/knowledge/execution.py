import re
import time

from django.db import transaction
from django.utils import timezone

from apps.enterprise.models import Organization
from modules.execution.infrastructure.artifacts import get_artifact_storage

from .extractors import DocumentExtractionError, extract_document
from .index_backend import replace_document_index
from .models import KnowledgeChunk, KnowledgeDocument
from .providers import ProviderUnavailable, answer_question, embed_texts
from .retrieval import chunk_sections


def execute_knowledge_index(run_payload, sink):
    snapshot = run_payload.get("definition_snapshot") or {}
    revision = int(snapshot["revision"])
    run_id = str(run_payload.get("run_id") or "")
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().select_related(
            "knowledge_base", "organization").get(pk=snapshot["document_id"])
        if document.is_deleted:
            return {"document_id": document.id, "deleted": True}
        if (
            document.pending_revision != revision
            or (run_id and str(document.indexing_run_id or "") != run_id)
        ):
            return {"document_id": document.id, "revision": revision, "superseded": True}
        document.status = KnowledgeDocument.Status.INDEXING
        document.error = ""
        document.error_code = ""
        document.metadata = {
            **document.metadata, "index_stage": "extracting", "index_progress": 10,
        }
        document.save(update_fields=[
            "status", "error", "error_code", "metadata", "updated_at",
        ])
    started = time.perf_counter()
    sink.emit("knowledge.index.progress", {"stage": "extracting", "progress": 10})
    try:
        if document.source_object_key:
            with get_artifact_storage().open(document.source_object_key) as handle:
                raw = handle.read()
        else:
            raw = document.content.encode("utf-8")
        sections = extract_document(raw, document.original_filename, document.mime_type)
        chunks = chunk_sections(
            sections,
            snapshot.get("chunk_size", 600),
            snapshot.get("chunk_overlap", 80),
        )
        if not chunks:
            raise DocumentExtractionError("no_extractable_text", "No extractable text was found.")
        sink.emit("knowledge.index.progress", {
            "stage": "embedding", "progress": 45, "chunk_count": len(chunks),
        })
        document.metadata = {
            **document.metadata,
            "index_stage": "embedding",
            "index_progress": 45,
            "pending_chunk_count": len(chunks),
        }
        progress_updated = KnowledgeDocument.objects.filter(
            pk=document.id,
            pending_revision=revision,
            indexing_run_id=run_id or document.indexing_run_id,
            is_deleted=False,
        ).update(metadata=document.metadata, updated_at=timezone.now())
        if not progress_updated:
            return {"document_id": document.id, "revision": revision, "superseded": True}
        vectors = [[] for _ in chunks]
        embedding_warning = ""
        embedding_usage = {}
        embedding_model_used = ""
        provider = snapshot.get("embedding_provider", "")
        model = snapshot.get("embedding_model", "")
        if provider or model:
            try:
                for offset in range(0, len(chunks), 64):
                    if sink.cancelled:
                        _mark_index_cancelled(document.id, revision, run_id)
                        return {"document_id": document.id, "revision": revision, "cancelled": True}
                    batch = chunks[offset:offset + 64]
                    batch_vectors = embed_texts(
                        document.organization, provider, model,
                        [item["content"] for item in batch],
                    )
                    embedding_model_used = getattr(batch_vectors, "model", "") or model
                    for key, value in getattr(batch_vectors, "usage", {}).items():
                        if isinstance(value, (int, float)):
                            embedding_usage[key] = embedding_usage.get(key, 0) + value
                    vectors[offset:offset + len(batch)] = batch_vectors
            except Exception as exc:
                if "Embedding dimension mismatch" in str(exc):
                    raise
                embedding_warning = str(exc)[:500]
                vectors = [[] for _ in chunks]
        if sink.cancelled:
            _mark_index_cancelled(document.id, revision, run_id)
            return {"document_id": document.id, "revision": revision, "cancelled": True}
        with transaction.atomic():
            document = KnowledgeDocument.objects.select_for_update().select_related(
                "knowledge_base", "organization").get(pk=document.id)
            if document.is_deleted:
                return {"document_id": document.id, "deleted": True}
            if (
                document.pending_revision != revision
                or (run_id and str(document.indexing_run_id or "") != run_id)
            ):
                return {"document_id": document.id, "revision": revision, "superseded": True}
            KnowledgeChunk.objects.filter(document=document, revision=revision).delete()
            chunk_objects = KnowledgeChunk.objects.bulk_create([
                KnowledgeChunk(
                    organization=document.organization,
                    document=document,
                    revision=revision,
                    position=index,
                    embedding=vectors[index],
                    **item,
                )
                for index, item in enumerate(chunks)
            ], batch_size=500)
            replace_document_index(document, chunk_objects)
            document.active_revision = revision
            document.pending_revision = 0
            document.status = KnowledgeDocument.Status.READY
            document.indexed_at = timezone.now()
            document.metadata = {
                **document.metadata,
                "chunk_count": len(chunks),
                "retrieval_mode": "hybrid" if any(vectors) else "lexical",
                "index_duration_ms": int((time.perf_counter() - started) * 1000),
                "embedding_warning": embedding_warning,
                "index_stage": "complete",
                "index_progress": 100,
            }
            document.save(update_fields=[
                "active_revision", "pending_revision", "status", "indexed_at",
                "metadata", "updated_at",
            ])
            KnowledgeChunk.objects.filter(document=document).exclude(revision=revision).delete()
        output = {
            "document_id": document.id,
            "revision": revision,
            "chunk_count": len(chunks),
            "retrieval_mode": document.metadata["retrieval_mode"],
            "usage": embedding_usage,
            "model": embedding_model_used,
        }
        sink.emit("knowledge.index.progress", {"stage": "complete", "progress": 100})
        sink.emit("output.snapshot", output)
        return output
    except Exception as exc:
        KnowledgeChunk.objects.filter(document=document, revision=revision).delete()
        with transaction.atomic():
            current = KnowledgeDocument.objects.select_for_update().get(pk=document.id)
            if (
                not current.is_deleted
                and current.pending_revision == revision
                and (not run_id or str(current.indexing_run_id or "") == run_id)
            ):
                current.pending_revision = 0
                current.error_code = getattr(exc, "code", "indexing_failed")
                current.error = str(exc)[:2000]
                current.metadata = {
                    **current.metadata, "index_stage": "failed",
                }
                current.status = (
                    KnowledgeDocument.Status.READY
                    if current.active_revision else KnowledgeDocument.Status.FAILED
                )
                current.save(update_fields=[
                    "pending_revision", "error_code", "error", "status", "metadata", "updated_at",
                ])
        raise


def _mark_index_cancelled(document_id, revision, run_id):
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if (
            document.is_deleted
            or document.pending_revision != revision
            or (run_id and str(document.indexing_run_id or "") != run_id)
        ):
            return
        document.pending_revision = 0
        document.error_code = "indexing_cancelled"
        document.error = "Indexing was cancelled."
        document.metadata = {
            **document.metadata, "index_stage": "cancelled",
        }
        document.status = (
            KnowledgeDocument.Status.READY
            if document.active_revision else KnowledgeDocument.Status.FAILED
        )
        document.save(update_fields=[
            "pending_revision", "error_code", "error", "status", "metadata", "updated_at",
        ])


def execute_knowledge_answer(run_payload, sink):
    snapshot = run_payload.get("definition_snapshot") or {}
    results = list(snapshot.get("results") or [])
    query = str((run_payload.get("input") or {}).get("query") or "")
    if not results:
        answer = "未找到足够依据。"
        usage = {}
        model = ""
    else:
        organization = Organization.objects.get(pk=run_payload["organization_id"])
        answer, usage, model = answer_question(
            organization,
            snapshot.get("answer_provider", ""),
            snapshot.get("answer_model", ""),
            query,
            results,
        )
        allowed = len(results)
        answer = re.sub(
            r"\[(\d+)\]",
            lambda match: match.group(0) if 1 <= int(match.group(1)) <= allowed else "",
            answer,
        )
    if sink.cancelled:
        return {}
    sink.emit("output.delta", {"text": answer})
    cited_indexes = {
        int(value) for value in re.findall(r"\[(\d+)\]", answer)
        if 1 <= int(value) <= len(results)
    }
    citations = [
        {"label": f"[{index}]", **result}
        for index, result in enumerate(results, start=1)
        if index in cited_indexes
    ]
    output = {
        "result": answer,
        "answer": answer,
        "citations": citations,
        "retrieval_mode": snapshot.get("retrieval_mode", "lexical"),
        "model": model,
        "usage": usage,
    }
    sink.emit("output.snapshot", output)
    return output

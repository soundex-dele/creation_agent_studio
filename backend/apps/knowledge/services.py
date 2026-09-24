import hashlib
import json
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from modules.execution.application.errors import IdempotencyKeyReused
from modules.execution.application.runs import create_run
from modules.execution.infrastructure.artifacts import (
    delete_artifact_object, persist_artifact,
)
from modules.execution.models import IdempotencyRecord, Run

from .models import KnowledgeDocument


ANSWER_OPERATION = "knowledge.answer.create"


def source_object_key(document, revision):
    extension = document.original_filename.rsplit(".", 1)[-1].lower() \
        if "." in document.original_filename else "txt"
    return (
        f"knowledge/{document.organization_id}/{document.knowledge_base_id}/"
        f"{document.id}/{revision}/source.{extension}"
    )


@transaction.atomic
def create_document(*, knowledge_base, actor, title, source_type, filename,
                    mime_type, content, run_context=None):
    checksum = hashlib.sha256(content).hexdigest()
    duplicate = KnowledgeDocument.objects.filter(
        knowledge_base=knowledge_base,
        checksum=checksum,
        is_deleted=False,
    ).first()
    if duplicate:
        raise ValueError(f"duplicate:{duplicate.id}")
    document = KnowledgeDocument.objects.create(
        organization=knowledge_base.organization,
        knowledge_base=knowledge_base,
        created_by=actor,
        title=title,
        source_type=source_type,
        original_filename=filename,
        mime_type=mime_type,
        byte_size=len(content),
        checksum=checksum,
        pending_revision=1,
    )
    object_key = source_object_key(document, 1)
    persist_artifact(object_key, content)
    try:
        document.source_object_key = object_key
        document.save(update_fields=["source_object_key", "updated_at"])
        run = create_run(
            organization=knowledge_base.organization,
            owner=actor,
            executor_kind="knowledge",
            executor_key="knowledge-index",
            source_type="knowledge_document",
            source_id=document.id,
            definition_snapshot={
                "document_id": document.id,
                "revision": 1,
                "chunk_size": knowledge_base.chunk_size,
                "chunk_overlap": knowledge_base.chunk_overlap,
                "embedding_provider": knowledge_base.embedding_provider,
                "embedding_model": knowledge_base.embedding_model,
            },
            input_data={"object_key": object_key, **(run_context or {})},
            max_attempts=3,
            retry_safe=True,
        )
    except Exception:
        try:
            delete_artifact_object(object_key)
        except Exception:
            pass
        raise
    document.indexing_run = run
    document.save(update_fields=["indexing_run", "updated_at"])
    return document, run


@transaction.atomic
def reindex_document(document, actor):
    if document.is_deleted:
        raise ValueError("Deleted documents cannot be reindexed.")
    revision = max(document.active_revision, document.pending_revision) + 1
    run = create_run(
        organization=document.organization,
        owner=actor,
        executor_kind="knowledge",
        executor_key="knowledge-index",
        source_type="knowledge_document",
        source_id=document.id,
        definition_snapshot={
            "document_id": document.id,
            "revision": revision,
            "chunk_size": document.knowledge_base.chunk_size,
            "chunk_overlap": document.knowledge_base.chunk_overlap,
            "embedding_provider": document.knowledge_base.embedding_provider,
            "embedding_model": document.knowledge_base.embedding_model,
        },
        input_data={"object_key": document.source_object_key,
                    **({"research_project_id": document.metadata["research_project_id"]}
                       if document.metadata.get("research_project_id") else {})},
        max_attempts=3,
        retry_safe=True,
    )
    document.pending_revision = revision
    document.indexing_run = run
    document.status = KnowledgeDocument.Status.PENDING
    document.error = ""
    document.error_code = ""
    document.save(update_fields=[
        "pending_revision", "indexing_run", "status", "error", "error_code", "updated_at",
    ])
    return run


def _fingerprint(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def replay_answer_run(*, organization, actor, request_data, idempotency_key):
    fingerprint = _fingerprint(request_data)
    existing = IdempotencyRecord.objects.for_organization(organization.id).filter(
        actor=actor, operation=ANSWER_OPERATION, key=idempotency_key,
    ).first()
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise IdempotencyKeyReused(
            "The idempotency key was already used with a different request")
    run_id = existing.response_body.get("run_id")
    if not run_id:
        return None
    return Run.objects.for_organization(organization.id).get(pk=run_id)


@transaction.atomic
def start_answer_run(*, organization, actor, query, results, retrieval_mode,
                     answer_provider, answer_model, idempotency_key, request_data):
    fingerprint = _fingerprint(request_data)
    existing = IdempotencyRecord.objects.for_organization(organization.id).filter(
        actor=actor, operation=ANSWER_OPERATION, key=idempotency_key,
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "The idempotency key was already used with a different request")
        run_id = existing.response_body.get("run_id")
        if run_id:
            return Run.objects.for_organization(organization.id).get(pk=run_id), True
    record = IdempotencyRecord.objects.create(
        organization=organization,
        actor=actor,
        operation=ANSWER_OPERATION,
        key=idempotency_key,
        request_fingerprint=fingerprint,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    run = create_run(
        organization=organization,
        owner=actor,
        executor_kind="knowledge",
        executor_key="knowledge-answer",
        source_type="knowledge_answer",
        source_id=str(uuid.uuid4()),
        definition_snapshot={
            "retrieval_mode": retrieval_mode,
            "results": results,
            "answer_provider": answer_provider,
            "answer_model": answer_model,
        },
        input_data={"query": query},
        max_attempts=2,
        retry_safe=True,
    )
    record.status = IdempotencyRecord.Status.COMPLETED
    record.response_status = 202
    record.response_body = {"run_id": str(run.id)}
    record.save(update_fields=["status", "response_status", "response_body"])
    return run, False

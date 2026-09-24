from django.conf import settings
from django.db import models

from modules.tenancy.models import TenantOwnedQuerySet


class KnowledgeBase(models.Model):
    # Internal application collections must never appear in organization knowledge APIs.
    scope = models.CharField(max_length=30, default="organization", db_index=True)
    organization = models.ForeignKey(
        "enterprise.Organization", on_delete=models.CASCADE,
        related_name="knowledge_bases",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    embedding_provider = models.CharField(max_length=100, blank=True)
    embedding_model = models.CharField(max_length=160, blank=True)
    answer_provider = models.CharField(max_length=100, blank=True)
    answer_model = models.CharField(max_length=160, blank=True)
    chunk_size = models.PositiveIntegerField(default=600)
    chunk_overlap = models.PositiveIntegerField(default=80)
    access_policy = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = "knowledge_bases"
        constraints = [models.UniqueConstraint(
            fields=["organization", "name"], name="unique_org_knowledge_base")]


class KnowledgeDocument(models.Model):
    class SourceType(models.TextChoices):
        TEXT = "text", "Text"
        UPLOAD = "upload", "Upload"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        INDEXING = "indexing", "Indexing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    knowledge_base = models.ForeignKey(
        KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    organization = models.ForeignKey(
        "enterprise.Organization", on_delete=models.CASCADE,
        related_name="knowledge_documents",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="knowledge_documents",
    )
    title = models.CharField(max_length=300)
    source_type = models.CharField(
        max_length=30, choices=SourceType.choices, default=SourceType.TEXT)
    source_uri = models.CharField(max_length=1000, blank=True)
    source_object_key = models.CharField(max_length=1000, blank=True)
    original_filename = models.CharField(max_length=300, blank=True)
    mime_type = models.CharField(max_length=160, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    # Kept for a lossless migration of the prototype. New content lives in object storage.
    content = models.TextField(blank=True)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    active_revision = models.PositiveIntegerField(default=0)
    pending_revision = models.PositiveIntegerField(default=0)
    indexing_run = models.ForeignKey(
        "execution.Run", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="indexed_knowledge_documents",
    )
    metadata = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = "knowledge_documents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["knowledge_base", "status", "is_deleted"]),
            models.Index(fields=["organization", "checksum"]),
        ]


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    organization = models.ForeignKey(
        "enterprise.Organization", on_delete=models.CASCADE,
        related_name="knowledge_chunks",
    )
    revision = models.PositiveIntegerField(default=1)
    position = models.PositiveIntegerField()
    content = models.TextField()
    lexical_text = models.TextField(blank=True)
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(default=list, blank=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    section_path = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = "knowledge_chunks"
        ordering = ["position"]
        constraints = [models.UniqueConstraint(
            fields=["document", "revision", "position"],
            name="unique_document_chunk_revision_position")]
        indexes = [
            models.Index(fields=["document", "revision", "position"]),
            models.Index(fields=["organization", "revision"]),
        ]

import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class ResearchProject(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    knowledge_base = models.OneToOneField("knowledge.KnowledgeBase", on_delete=models.PROTECT)
    title = models.CharField(max_length=200)
    objective = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    cleanup_pending = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        indexes = [models.Index(fields=["organization", "application", "owner"])]


class ResearchSource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(ResearchProject, on_delete=models.CASCADE, related_name="sources")
    document = models.OneToOneField("knowledge.KnowledgeDocument", on_delete=models.PROTECT)
    origin = models.JSONField(default=dict)
    removed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ResearchResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(ResearchProject, on_delete=models.CASCADE, related_name="results")
    kind = models.CharField(max_length=30)
    instruction = models.TextField(blank=True)
    objective = models.TextField()
    source_snapshot = models.JSONField(default=list)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    run = models.OneToOneField("execution.Run", null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["project", "request_key"], name="research_generation_key")]


class ResearchExport(models.Model):
    result = models.ForeignKey(ResearchResult, on_delete=models.CASCADE, related_name="exports")
    key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    target = models.CharField(max_length=20)
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["result", "key"], name="research_export_key")]

import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class PromptSession(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    mode = models.CharField(max_length=16, default="generate")
    topic = models.TextField(blank=True)
    original = models.TextField(blank=True)
    objective = models.TextField(blank=True)
    scene = models.CharField(max_length=20, default="auto")
    detected_scene = models.CharField(max_length=20, default="general")
    language = models.CharField(max_length=8, default="zh")
    questions = models.JSONField(default=list)
    answers = models.JSONField(default=dict)
    analysis = models.JSONField(default=dict)
    rounds = models.PositiveSmallIntegerField(default=0)
    revision = models.PositiveIntegerField(default=0)
    results_stale = models.BooleanField(default=False)
    favorite = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prompt_master_session"
        ordering = ["-updated_at", "id"]
        indexes = [models.Index(fields=["organization", "owner", "application", "-updated_at"], name="prompt_private_history")]


class PromptVersion(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(PromptSession, on_delete=models.CASCADE, related_name="versions")
    source = models.CharField(max_length=16)
    standard = models.TextField()
    concise = models.TextField()
    assumptions = models.JSONField(default=list)
    health = models.JSONField(default=list)
    changes = models.JSONField(default=list)
    constraints = models.JSONField(default=list)
    health_stale = models.BooleanField(default=False)
    basis = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_master_version"
        ordering = ["-created_at", "id"]


class PromptTask(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(PromptSession, on_delete=models.CASCADE, related_name="tasks")
    run = models.OneToOneField("execution.Run", null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=16)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="queued")
    error = models.TextField(blank=True)
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_master_task"
        ordering = ["-created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["session", "request_key"], name="prompt_task_request_key")]

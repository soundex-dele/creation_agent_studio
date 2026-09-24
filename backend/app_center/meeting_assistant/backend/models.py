import uuid
from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class Recording(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=[("meeting", "会议"), ("interview", "访谈")])
    recorded_on = models.DateField()
    language = models.CharField(max_length=10, default="zh")
    object_key = models.CharField(max_length=500)
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    duration = models.FloatField(default=0)
    segments = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)
    analysis_version = models.PositiveIntegerField(default=0)
    analysis = models.JSONField(default=dict)
    stage = models.CharField(max_length=20, default="queued")
    error = models.CharField(max_length=500, blank=True)
    active_run = models.ForeignKey("execution.Run", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "meeting_recordings"
        ordering = ["-updated_at", "id"]
        indexes = [models.Index(fields=["organization", "application", "owner"], name="meeting_record_scope")]


class ActionItem(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recording = models.ForeignKey(Recording, on_delete=models.CASCADE, related_name="actions")
    analysis_version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(default=2)
    due_date = models.DateField(null=True, blank=True)
    segment_ids = models.JSONField(default=list)
    todo = models.ForeignKey("ideas_todos.Todo", null=True, blank=True, on_delete=models.SET_NULL)
    # Keep confirmation even if the user later deletes the independent todo.
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "meeting_actions"
        ordering = ["id"]


class DocumentExport(TenantOwnedModel):
    recording = models.ForeignKey(Recording, on_delete=models.CASCADE, related_name="exports")
    key = models.CharField(max_length=160)
    kind = models.CharField(max_length=20)
    version = models.PositiveIntegerField()
    document = models.ForeignKey("online_documents.Document", null=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = "meeting_exports"
        constraints = [models.UniqueConstraint(fields=["recording", "key"], name="meeting_export_key")]

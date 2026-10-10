import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class CleanerHost(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    heartbeat_at = models.DateTimeField(null=True)


class CleanerTask(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    host = models.CharField(max_length=64, db_index=True)
    kind = models.CharField(max_length=12)  # scan / cleanup
    state = models.CharField(max_length=16, default="queued", db_index=True)
    request_key = models.CharField(max_length=160)
    parameters = models.JSONField(default=dict)
    source = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE)
    preview = models.OneToOneField("CleanerPreview", null=True, blank=True, on_delete=models.CASCADE, related_name="cleanup")
    cancel_requested = models.BooleanField(default=False)
    processed = models.PositiveBigIntegerField(default=0)
    total_bytes = models.PositiveBigIntegerField(default=0)
    skipped = models.PositiveBigIntegerField(default=0)
    deleted_bytes = models.PositiveBigIntegerField(default=0)
    free_before = models.JSONField(default=dict)
    free_after = models.JSONField(default=dict)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    heartbeat_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner", "host", "request_key"], name="cleaner_request_key")]


class CleanerEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(CleanerTask, on_delete=models.CASCADE, related_name="entries")
    path = models.TextField()
    parent = models.TextField()
    kind = models.CharField(max_length=12)  # file / directory
    size = models.PositiveBigIntegerField(default=0)
    modified_at = models.DateTimeField(null=True)
    identity = models.JSONField(default=dict)
    cleanable = models.BooleanField(default=False)


class CleanerPreview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(CleanerTask, on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    entry_ids = models.JSONField(default=list)
    total_bytes = models.PositiveBigIntegerField(default=0)
    expires_at = models.DateTimeField()


class CleanerResult(models.Model):
    task = models.ForeignKey(CleanerTask, on_delete=models.CASCADE, related_name="results")
    entry = models.ForeignKey(CleanerEntry, on_delete=models.CASCADE)
    state = models.CharField(max_length=12, default="pending")
    reason = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["task", "entry"], name="cleaner_result_entry")]

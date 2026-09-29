import uuid
from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class Account(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source_url = models.URLField(max_length=1000)
    platform_id = models.CharField(max_length=200, blank=True)
    name = models.CharField(max_length=200, blank=True)
    group = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    profile = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner", "source_url"], name="dy_account_source_unique")]


class Work(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="works")
    platform_id = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict)
    media_key = models.CharField(max_length=300, blank=True)
    media_urls = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "platform_id"], name="dy_work_platform_unique")]


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="tasks")
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    input = models.JSONField(default=dict)
    output = models.JSONField(default=dict)
    stage = models.CharField(max_length=50, default="queued")
    error = models.CharField(max_length=500, blank=True)
    progress = models.JSONField(default=dict)
    run = models.OneToOneField("execution.Run", null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["account", "request_key"], name="dy_task_key_unique")]


class Snapshot(models.Model):
    batch = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="snapshots")
    work = models.ForeignKey(Work, on_delete=models.CASCADE)
    data = models.JSONField(default=dict)
    captured_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "work"], name="dy_batch_work_unique")]


class ScriptVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="versions")
    revision = models.PositiveIntegerField()
    content = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision"]
        constraints = [models.UniqueConstraint(fields=["task", "revision"], name="dy_script_revision_unique")]


class CollectorConfig(TenantOwnedModel):
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    user_agent = models.CharField(max_length=2000)
    encrypted_cookies = models.TextField()
    screen = models.CharField(max_length=20, default="1920x1080")
    language = models.CharField(max_length=50, default="zh-CN")
    timezone = models.CharField(max_length=100, default="Asia/Shanghai")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner"], name="dy_collector_owner_unique")]

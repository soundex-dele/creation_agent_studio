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
    is_owned = models.BooleanField(default=False)
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
    organization = models.ForeignKey("enterprise.Organization", on_delete=models.CASCADE)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
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
        constraints = [models.UniqueConstraint(fields=["account", "request_key"], name="dy_task_key_unique"),
            models.UniqueConstraint(fields=["organization", "application", "owner", "request_key"], condition=models.Q(account__isnull=True), name="dy_workspace_task_key")]

    def save(self, *args, **kwargs):
        if self.account_id:
            self.organization_id = self.account.organization_id
            self.application_id = self.account.application_id
            self.owner_id = self.account.owner_id
        super().save(*args, **kwargs)


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
    cookies = models.TextField()
    screen = models.CharField(max_length=20, default="1920x1080")
    language = models.CharField(max_length=50, default="zh-CN")
    timezone = models.CharField(max_length=100, default="Asia/Shanghai")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner"], name="dy_collector_owner_unique")]


class PrivateRecord(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE, related_name="+")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-updated_at", "id"]


class CreatorProfile(PrivateRecord):
    account = models.OneToOneField(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='creator_profile')
    content_pillars = models.TextField(blank=True)
    content_boundaries = models.TextField(blank=True)
    shared_inspiration_ids = models.JSONField(default=list, blank=True)
    active_version = models.ForeignKey('VoiceVersion', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    name = models.CharField(max_length=100)
    positioning = models.TextField(blank=True)
    audience = models.TextField(blank=True)
    experiences = models.TextField(blank=True)
    products = models.TextField(blank=True)
    voice = models.TextField(blank=True)
    conditions = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner"], condition=models.Q(is_default=True), name="dy_default_profile")]


class VoiceSample(PrivateRecord):
    profile = models.ForeignKey(CreatorProfile, on_delete=models.CASCADE, related_name='voice_samples')
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.SET_NULL)
    source_task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=300)
    text = models.TextField(blank=True)
    usage = models.CharField(max_length=20, default='style')
    source_url = models.URLField(max_length=1000, blank=True)


class VoiceVersion(PrivateRecord):
    profile = models.ForeignKey(CreatorProfile, on_delete=models.CASCADE, related_name='voice_versions')
    number = models.PositiveIntegerField()
    content = models.JSONField(default=dict)
    evidence = models.JSONField(default=list)
    source_task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=['profile', 'number'], name='dy_voice_version_number')]


class Inspiration(PrivateRecord):
    title = models.CharField(max_length=300)
    kind = models.CharField(max_length=20, default="work")
    text = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.SET_NULL)
    source_task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)
    source_ref = models.CharField(max_length=150, blank=True)
    source_time = models.FloatField(null=True, blank=True)


class Idea(PrivateRecord):
    title = models.CharField(max_length=300)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    status = models.CharField(max_length=20, default="research")
    position = models.IntegerField(default=0)
    inspiration = models.ForeignKey(Inspiration, null=True, blank=True, on_delete=models.SET_NULL)
    source_task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)


class TaskSource(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="source_links")
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.CASCADE)
    source_task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="dependents")


class MetricObservation(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="observations")
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    captured_at = models.DateTimeField()
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["captured_at", "id"]
        constraints = [models.UniqueConstraint(fields=["work", "task"], name="dy_observation_once")]


class CommentBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="comment_batch")
    work = models.ForeignKey(Work, on_delete=models.CASCADE)
    complete = models.BooleanField(default=False)
    warning = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Comment(models.Model):
    batch = models.ForeignKey(CommentBatch, on_delete=models.CASCADE, related_name="comments")
    platform_id = models.CharField(max_length=100)
    parent_id = models.CharField(max_length=100, blank=True)
    text = models.TextField()
    likes = models.PositiveBigIntegerField(null=True)
    published_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["batch", "platform_id"], name="dy_comment_once")]


class Publication(PrivateRecord):
    work = models.ForeignKey(Work, on_delete=models.CASCADE)
    idea = models.ForeignKey(Idea, null=True, blank=True, on_delete=models.SET_NULL)
    script_version = models.ForeignKey(ScriptVersion, null=True, blank=True, on_delete=models.SET_NULL)
    theme = models.CharField(max_length=300, blank=True)
    title = models.CharField(max_length=300, blank=True)
    hook = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["work"], name="dy_publication_work")]


class Subscription(PrivateRecord):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="subscription")
    enabled = models.BooleanField(default=False)
    interval_hours = models.PositiveIntegerField(default=24)
    count = models.PositiveIntegerField(default=50)
    tracked_works = models.ManyToManyField(Work, blank=True)
    rules = models.JSONField(default=dict)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    blocked_reason = models.CharField(max_length=500, blank=True)


class Notification(PrivateRecord):
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=300)
    body = models.JSONField(default=dict)
    dedup_key = models.CharField(max_length=200)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.CASCADE)
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.CASCADE)
    read = models.BooleanField(default=False)

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner", "dedup_key"], name="dy_notification_once")]


class Digest(PrivateRecord):
    day = models.DateField()
    body = models.JSONField(default=dict)

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["organization", "application", "owner", "day"], name="dy_digest_once")]

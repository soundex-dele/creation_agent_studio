import uuid
from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class Project(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'id']


class Snapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='snapshots')
    origin = models.JSONField(default=dict)
    files = models.JSONField(default=dict)
    coverage = models.JSONField(default=dict)
    digest = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, default='pending')
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    snapshot = models.ForeignKey(Snapshot, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20)
    options = models.JSONField(default=dict)
    output = models.JSONField(default=dict)
    run = models.OneToOneField('execution.Run', null=True, on_delete=models.SET_NULL, related_name='repo_task')
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['project', 'request_key'], name='repo_task_key')]


class Content(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='contents')
    analysis = models.ForeignKey(Task, on_delete=models.PROTECT)
    generation = models.OneToOneField(Task, on_delete=models.PROTECT, related_name='generated_content')
    title = models.CharField(max_length=200)
    draft = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Version(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='versions')
    revision = models.PositiveIntegerField()
    document = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-revision']
        constraints = [models.UniqueConstraint(fields=['content', 'revision'], name='repo_content_revision')]


class Handoff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='handoffs')
    version = models.ForeignKey(Version, on_delete=models.PROTECT)
    target_application = models.ForeignKey('applications.Application', on_delete=models.PROTECT)
    kind = models.CharField(max_length=20)
    draft = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    target_id = models.CharField(max_length=100, blank=True)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['project', 'request_key'], name='repo_handoff_key')]

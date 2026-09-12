"""用户手工编排和运行的多应用工作流。"""
import uuid

from django.conf import settings
from django.db import models


class Workflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE,
        related_name='workflows')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='owned_workflows')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, default='workflow')
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workflows'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class WorkflowStep(models.Model):
    """工作流中的有序应用引用；第一版不做自动依赖调度。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow, on_delete=models.CASCADE, related_name='steps')
    application = models.ForeignKey(
        'applications.Application', on_delete=models.PROTECT,
        related_name='workflow_steps')
    name = models.CharField(max_length=200, blank=True)
    config = models.JSONField(default=dict, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'workflow_steps'
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(
            fields=['workflow', 'order'], name='unique_workflow_step_order')]


class WorkflowRun(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', '进行中'
        COMPLETED = 'completed', '已完成'
        ARCHIVED = 'archived', '已归档'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow, on_delete=models.PROTECT, related_name='runs')
    project = models.ForeignKey(
        'projects.Project', on_delete=models.PROTECT, related_name='workflow_runs')
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE,
        related_name='workflow_runs')
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='workflow_runs')
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE)
    working_directory = models.CharField(max_length=1000, blank=True, default='')
    selected_step = models.ForeignKey(
        WorkflowStep, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    selected_step_run = models.ForeignKey(
        'WorkflowStepRun', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workflow_runs'
        ordering = ['-updated_at']


class WorkflowStepRun(models.Model):
    class Status(models.TextChoices):
        IDLE = 'idle', '未开始'
        ACTIVE = 'active', '使用中'
        COMPLETED = 'completed', '已完成'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_run = models.ForeignKey(
        WorkflowRun, on_delete=models.CASCADE, related_name='step_runs')
    workflow_step = models.ForeignKey(
        WorkflowStep, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='runs')
    source_step_id = models.UUIDField()
    application = models.ForeignKey(
        'applications.Application', on_delete=models.PROTECT,
        related_name='workflow_step_runs')
    application_revision = models.ForeignKey(
        'catalog.ApplicationRevision', on_delete=models.PROTECT,
        related_name='workflow_step_runs')
    name = models.CharField(max_length=200, blank=True)
    config = models.JSONField(default=dict, blank=True)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IDLE)
    state = models.JSONField(default=dict, blank=True)
    working_directory = models.CharField(max_length=1000, blank=True, default='')
    last_opened_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workflow_step_runs'
        ordering = ['order', 'id']

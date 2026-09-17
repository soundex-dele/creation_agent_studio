"""用户手工编排和运行的多应用工作流。"""
import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedQuerySet


class Workflow(models.Model):
    class ExecutionMode(models.TextChoices):
        MANUAL = 'manual', '手动执行'
        AUTOMATIC = 'automatic', '自动执行'

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
    execution_mode = models.CharField(
        max_length=20,
        choices=ExecutionMode.choices,
        default=ExecutionMode.AUTOMATIC,
    )
    output_mapping = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = 'workflows'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class WorkflowStep(models.Model):
    """A stable node in the workflow DAG."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow, on_delete=models.CASCADE, related_name='steps')
    application = models.ForeignKey(
        'applications.Application', on_delete=models.PROTECT,
        related_name='workflow_steps')
    name = models.CharField(max_length=200, blank=True)
    key = models.SlugField(max_length=100)
    config = models.JSONField(default=dict, blank=True)
    depends_on = models.JSONField(default=list, blank=True)
    condition = models.JSONField(default=dict, blank=True)
    max_attempts = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'workflow_steps'
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'order'], name='unique_workflow_step_order'),
            models.UniqueConstraint(
                fields=['workflow', 'key'], name='unique_workflow_step_key'),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name='workflow_step_attempts_at_least_one'),
        ]

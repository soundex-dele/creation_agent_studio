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

"""
Models for agents app.
"""
from django.db import models
from apps.users.models import User
from modules.tenancy.models import TenantOwnedQuerySet


class AgentCategory(models.Model):
    """智能体分类"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']
        db_table = 'agent_categories'

    def __str__(self):
        return self.name


class Agent(models.Model):
    """智能体及其当前运行配置。"""
    category = models.ForeignKey(
        AgentCategory,
        on_delete=models.CASCADE,
        related_name='agents'
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, blank=True)
    system_prompt = models.TextField()
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='agents'
    )
    model_config = models.JSONField(default=dict, blank=True)
    tool_config = models.JSONField(default=list, blank=True)
    skill_config = models.JSONField(default=list, blank=True)
    knowledge_config = models.JSONField(default=list, blank=True)
    guardrail_config = models.JSONField(default=dict, blank=True)
    workflow_config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        ordering = ['category__order', 'name']
        db_table = 'agents'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'slug'], name='unique_agent_slug_per_org'),
            models.UniqueConstraint(
                fields=['slug'], condition=models.Q(organization__isnull=True),
                name='unique_global_agent_slug')]

    def __str__(self):
        return self.name


class AgentSkillBinding(models.Model):
    """Agent 对 Skill 的声明式引用。"""

    class Mode(models.TextChoices):
        REQUIRED = 'required', '必需'
        DEFAULT = 'default', '默认'
        OPTIONAL = 'optional', '可选'

    agent = models.ForeignKey(
        Agent, on_delete=models.CASCADE, related_name='skill_bindings')
    skill = models.ForeignKey(
        'applications.Skill', on_delete=models.PROTECT, related_name='agent_bindings')
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.DEFAULT)
    config = models.JSONField(default=dict, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'agent_skill_bindings'
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(
            fields=['agent', 'skill'],
            name='unique_agent_skill_binding')]

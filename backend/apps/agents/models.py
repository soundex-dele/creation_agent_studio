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
    """Stable agent identity and catalog metadata."""
    class Kind(models.TextChoices):
        STANDARD = 'standard', '标准智能体'
        SUPERVISOR = 'supervisor', 'AI 分身'

    category = models.ForeignKey(
        AgentCategory,
        on_delete=models.CASCADE,
        related_name='agents'
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, blank=True)
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.STANDARD, db_index=True,
    )
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='agents'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        ordering = ['category__order', 'name']
        db_table = 'agents'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'slug'],
                condition=models.Q(is_active=True),
                name='unique_agent_slug_per_org',
            ),
            models.UniqueConstraint(
                fields=['slug'],
                condition=models.Q(organization__isnull=True, is_active=True),
                name='unique_global_agent_slug',
            ),
        ]

    def __str__(self):
        return self.name


class SupervisorProfile(models.Model):
    """Stable sharing metadata for an Agent-backed supervisor."""

    class Visibility(models.TextChoices):
        PRIVATE = 'private', '仅自己'
        ORGANIZATION = 'organization', '组织共享'

    agent = models.OneToOneField(
        Agent,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='supervisor_profile',
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'supervisor_profiles'

    def __str__(self):
        return f'{self.agent.name} ({self.visibility})'

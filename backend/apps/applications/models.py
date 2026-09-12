"""
Models for applications app (应用中心).
"""
import uuid

from django.db import models
from apps.users.models import User
from modules.tenancy.models import TenantOwnedQuerySet


class ApplicationCategory(models.Model):
    """应用分类"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']
        db_table = 'application_categories'

    def __str__(self):
        return self.name


class Application(models.Model):
    """Stable application identity and catalog metadata."""

    class Kind(models.TextChoices):
        CHAT = 'chat', '聊天应用'
        TASK = 'task', '任务应用'
        CUSTOM = 'custom', '自定义应用'
    category = models.ForeignKey(
        ApplicationCategory,
        on_delete=models.CASCADE,
        related_name='applications'
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, blank=True)
    # Accent color (hex, e.g. '#2e1a1a') used by the frontend thumbnail gradient.
    color = models.CharField(max_length=20, blank=True, default='')
    tags = models.JSONField(default=list, blank=True)
    developer = models.CharField(max_length=100, blank=True, default='')
    screenshots = models.JSONField(default=list, blank=True)
    usage_count = models.IntegerField(default=0)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='applications'
    )
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.CUSTOM)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        ordering = ['category__order', 'name']
        db_table = 'applications'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'slug'],
            name='unique_application_slug_per_org')]

    def __str__(self):
        return self.name


class Skill(models.Model):
    """Skill 及其当前内容。"""

    class Visibility(models.TextChoices):
        PRIVATE = 'private', '私有'
        ORGANIZATION = 'organization', '组织'
        PUBLIC = 'public', '公开'

    class SourceType(models.TextChoices):
        BUNDLED = 'bundled', '内置'
        UPLOAD = 'upload', '上传'
        GIT = 'git', 'Git'
        REGISTRY = 'registry', '注册中心'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='skills',
    )
    slug = models.SlugField(max_length=120)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE)
    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='owned_skills')
    source_type = models.CharField(
        max_length=20, choices=SourceType.choices, default=SourceType.BUNDLED)
    source_uri = models.CharField(max_length=500, blank=True)
    artifact_key = models.CharField(max_length=500, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = 'skills'
        ordering = ['name']
        constraints = [models.UniqueConstraint(
            fields=['organization', 'slug'], name='unique_skill_slug_per_org')]

    def __str__(self):
        return self.name


class ChatApplication(models.Model):
    """Marker subtype for applications whose definition follows the chat schema.

    Runtime configuration deliberately lives in the catalog draft/revision, not
    on this stable identity.  This keeps metadata and executable definitions
    from becoming two independently editable sources of truth.
    """

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, primary_key=True,
        related_name='chat_application')

    class Meta:
        db_table = 'chat_applications'

    def __str__(self):
        return self.application.name

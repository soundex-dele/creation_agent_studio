"""Organization-scoped data model for the short-video creation workspace."""
from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from modules.tenancy.models import TenantOwnedModel


def _safe_name(name: str) -> str:
    stem = Path(name).stem[:80] or "file"
    suffix = Path(name).suffix[:16].lower()
    return f"{stem}{suffix}"


def asset_upload_path(instance: "MediaAsset", filename: str) -> str:
    return (
        f"creation_toolbox/{instance.organization_id}/projects/"
        f"{instance.project_id}/assets/{uuid.uuid4().hex}_{_safe_name(filename)}"
    )


def recording_upload_path(instance: "Recording", filename: str) -> str:
    project = str(instance.project_id or "unassigned")
    return (
        f"creation_toolbox/{instance.organization_id}/projects/{project}/"
        f"recordings/{uuid.uuid4().hex}_{_safe_name(filename)}"
    )


def deliverable_upload_path(instance: "VideoDeliverable", filename: str) -> str:
    return (
        f"creation_toolbox/{instance.organization_id}/projects/"
        f"{instance.project_id}/deliverables/{uuid.uuid4().hex}_{_safe_name(filename)}"
    )


class Platform(models.TextChoices):
    DOUYIN = "douyin", "抖音"
    KUAISHOU = "kuaishou", "快手"
    WECHAT_CHANNELS = "wechat_channels", "视频号"
    XIAOHONGSHU = "xiaohongshu", "小红书"
    BILIBILI = "bilibili", "B站"
    OTHER = "other", "其他"


class CreationWorkspace(TenantOwnedModel):
    application = models.OneToOneField(
        "applications.Application",
        on_delete=models.CASCADE,
        related_name="creation_toolbox_workspace",
    )
    name = models.CharField(max_length=120, default="创作工具箱")
    storage_mode = models.CharField(max_length=32, default="managed")
    audio_sample_rate = models.PositiveIntegerField(default=44100)
    transcription_language = models.CharField(max_length=24, default="zh-CN")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_workspaces"


class TopicIdea(TenantOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待评估"
        READY = "ready", "待创作"
        ADOPTED = "adopted", "已采用"
        POSTPONED = "postponed", "暂缓"
        ARCHIVED = "archived", "已归档"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="topics"
    )
    title = models.CharField(max_length=200)
    normalized_title = models.CharField(max_length=200, db_index=True)
    notes = models.TextField(blank=True)
    source_name = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    target_platforms = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creation_topics"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_creation_topics",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_topics"
        ordering = ["-updated_at", "title"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="ct_topic_workspace_status"),
        ]


class CreationProject(TenantOwnedModel):
    class Stage(models.TextChoices):
        PLANNING = "planning", "策划"
        SCRIPTING = "scripting", "脚本"
        MATERIALS = "materials", "素材"
        PRODUCING = "producing", "制作中"
        REVIEW = "review", "待审核"
        PUBLISHED = "published", "已发布"
        RETROSPECTIVE = "retrospective", "复盘完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="projects"
    )
    topic = models.ForeignKey(
        TopicIdea,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    stage = models.CharField(
        max_length=24, choices=Stage.choices, default=Stage.PLANNING, db_index=True
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_creation_projects",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_creation_projects",
    )
    planned_publish_at = models.DateTimeField(null=True, blank=True, db_index=True)
    target_platforms = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    stage_changed_at = models.DateTimeField(default=timezone.now)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creation_projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_projects"
        ordering = ["-updated_at", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"], name="unique_creation_project_name"
            )
        ]


class ProjectStageEvent(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        CreationProject, on_delete=models.CASCADE, related_name="stage_events"
    )
    from_stage = models.CharField(max_length=24, choices=CreationProject.Stage.choices)
    to_stage = models.CharField(max_length=24, choices=CreationProject.Stage.choices)
    note = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="creation_stage_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "creation_toolbox_stage_events"
        ordering = ["-created_at"]


class MaterialFolder(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        CreationProject, on_delete=models.CASCADE, related_name="folders"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "creation_toolbox_folders"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "parent", "name"], name="unique_creation_folder_name"
            )
        ]


class MediaAsset(TenantOwnedModel):
    class Kind(models.TextChoices):
        IMAGE = "image", "图片"
        VIDEO = "video", "视频"
        AUDIO = "audio", "音频"
        DOCUMENT = "document", "文档"
        OTHER = "other", "其他"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        CreationProject, on_delete=models.CASCADE, related_name="assets"
    )
    folder = models.ForeignKey(
        MaterialFolder,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to=asset_upload_path, max_length=500)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creation_assets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_assets"
        ordering = ["kind", "name"]


class Recording(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="recordings"
    )
    project = models.ForeignKey(
        CreationProject,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recordings",
    )
    name = models.CharField(max_length=255)
    audio = models.FileField(upload_to=recording_upload_path, max_length=500)
    mime_type = models.CharField(max_length=120, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    transcription = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creation_recordings"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_recordings"
        ordering = ["-created_at"]


class Copywriting(TenantOwnedModel):
    class Style(models.TextChoices):
        FUNNY = "funny", "搞笑"
        EMOTIONAL = "emotional", "情感"
        INFORMATIVE = "informative", "干货"
        SCIENCE = "science", "科普"
        MARKETING = "marketing", "营销"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="copywritings"
    )
    project = models.ForeignKey(
        CreationProject,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="copywritings",
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    style = models.CharField(max_length=20, choices=Style.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creation_copywritings"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_copywritings"
        ordering = ["-updated_at"]


class Script(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="scripts"
    )
    project = models.ForeignKey(
        CreationProject,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scripts",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creation_scripts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_scripts"
        ordering = ["-updated_at"]


class VideoDeliverable(TenantOwnedModel):
    class ReviewStatus(models.TextChoices):
        DRAFT = "draft", "草稿"
        PENDING = "pending", "待审核"
        APPROVED = "approved", "已通过"
        CHANGES_REQUESTED = "changes_requested", "需修改"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        CreationProject, on_delete=models.CASCADE, related_name="deliverables"
    )
    name = models.CharField(max_length=200)
    version_label = models.CharField(max_length=80, default="v1")
    platform = models.CharField(max_length=24, choices=Platform.choices, blank=True)
    file = models.FileField(
        upload_to=deliverable_upload_path, max_length=500, null=True, blank=True
    )
    external_url = models.URLField(max_length=1000, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    review_status = models.CharField(
        max_length=24,
        choices=ReviewStatus.choices,
        default=ReviewStatus.DRAFT,
        db_index=True,
    )
    review_note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="creation_deliverables",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_creation_deliverables",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_deliverables"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(file__isnull=False) | ~models.Q(external_url=""),
                name="creation_deliverable_has_source",
            )
        ]


class Publication(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="publications"
    )
    project = models.ForeignKey(
        CreationProject, on_delete=models.CASCADE, related_name="publications"
    )
    deliverable = models.ForeignKey(
        VideoDeliverable,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="publications",
    )
    platform = models.CharField(max_length=24, choices=Platform.choices, db_index=True)
    platform_name = models.CharField(max_length=80, blank=True)
    account_name = models.CharField(max_length=160)
    title = models.CharField(max_length=300, blank=True)
    external_post_id = models.CharField(max_length=200, blank=True)
    post_url = models.URLField(max_length=1000, blank=True)
    published_at = models.DateTimeField(db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="creation_publications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_publications"
        ordering = ["-published_at"]
        indexes = [
            models.Index(
                fields=["workspace", "platform"],
                name="ct_pub_workspace_platform",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "platform", "account_name", "external_post_id"],
                condition=~models.Q(external_post_id=""),
                name="unique_creation_publication_external_id",
            ),
            models.UniqueConstraint(
                fields=["workspace", "platform", "account_name", "post_url"],
                condition=~models.Q(post_url=""),
                name="unique_creation_publication_url",
            ),
        ]


class MetricSnapshot(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication = models.ForeignKey(
        Publication, on_delete=models.CASCADE, related_name="metric_snapshots"
    )
    observed_on = models.DateField(db_index=True)
    impressions = models.PositiveBigIntegerField(default=0)
    views = models.PositiveBigIntegerField(default=0)
    completions = models.PositiveBigIntegerField(default=0)
    likes = models.PositiveBigIntegerField(default=0)
    comments = models.PositiveBigIntegerField(default=0)
    shares = models.PositiveBigIntegerField(default=0)
    saves = models.PositiveBigIntegerField(default=0)
    followers_gained = models.PositiveBigIntegerField(default=0)
    conversions = models.PositiveBigIntegerField(default=0)
    average_watch_seconds = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    extra_metrics = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="creation_metric_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_metric_snapshots"
        ordering = ["-observed_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["publication", "observed_on"],
                name="unique_creation_metric_snapshot_day",
            )
        ]


class Scene(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    script = models.ForeignKey(Script, on_delete=models.CASCADE, related_name="scenes")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image_asset = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="scenes"
    )
    duration_seconds = models.PositiveIntegerField(default=5)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "creation_toolbox_scenes"
        ordering = ["order", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["script", "order"], name="unique_scene_order")
        ]

"""Organization-scoped data model for the short-video creation workspace."""
from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

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


class CreationProject(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        CreationWorkspace, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
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


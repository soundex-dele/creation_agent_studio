import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class AnimationAsset(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    object_key = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    duration = models.FloatField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    category = models.CharField(max_length=40, default="素材")
    archived = models.BooleanField(default=False)

    class Meta:
        db_table = "animation_studio_assets"


class AnimationProject(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, default="未命名作品")
    archived = models.BooleanField(default=False)
    draft = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "animation_studio_projects"
        ordering = ["-updated_at", "-id"]


class AnimationVersion(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(AnimationProject, on_delete=models.CASCADE, related_name="versions")
    run = models.OneToOneField("execution.Run", on_delete=models.PROTECT, related_name="animation_version")
    document = models.JSONField(default=dict)
    note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Keep the run link so history import cannot recreate a removed version.
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "animation_studio_versions"
        ordering = ["-created_at", "-id"]


class AnimationPreset(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=[("template", "模板"), ("brand", "品牌")])
    name = models.CharField(max_length=100)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "animation_studio_presets"


class AnimationSpeechConfig(TenantOwnedModel):
    application = models.OneToOneField("applications.Application", on_delete=models.CASCADE)
    app_id = models.CharField(max_length=200, blank=True)
    resource_id = models.CharField(max_length=200, default="seed-tts-2.0")
    secret_ref = models.CharField(max_length=200, blank=True)
    voices = models.JSONField(default=list)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "animation_studio_speech"


class AnimationBatch(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    run = models.OneToOneField("execution.Run", on_delete=models.PROTECT, null=True)
    rows = models.JSONField(default=list)
    template = models.JSONField(default=dict)
    export_options = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "animation_studio_batches"

import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class DriveSpace(TenantOwnedModel):
    """One lock/quota boundary per organization and owner, across installations."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "owner"], name="drive_space_owner")]


class DriveEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(DriveSpace, on_delete=models.CASCADE)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=240)
    kind = models.CharField(max_length=10, choices=[("folder", "Folder"), ("file", "File")])
    size = models.PositiveBigIntegerField(default=0)
    media_type = models.CharField(max_length=100, blank=True)
    object_key = models.CharField(max_length=200, blank=True)
    trash_batch = models.UUIDField(null=True, blank=True, db_index=True)
    trash_root = models.BooleanField(default=False)
    purge_pending = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["space", "application", "parent"], name="drive_entry_scope")]


class DriveUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(DriveSpace, on_delete=models.CASCADE)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    parent = models.ForeignKey(DriveEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploads")
    entry = models.ForeignKey(DriveEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="source_uploads")
    name = models.CharField(max_length=240)
    size = models.PositiveBigIntegerField()
    last_modified = models.BigIntegerField(default=0)
    offset = models.PositiveBigIntegerField(default=0)
    chunk_size = models.PositiveIntegerField(default=8 * 1024 ** 2)
    state = models.CharField(max_length=20, default="uploading", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)


class DriveChunk(models.Model):
    upload = models.ForeignKey(DriveUpload, on_delete=models.CASCADE, related_name="chunks")
    offset = models.PositiveBigIntegerField()
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["upload", "offset"], name="drive_chunk_offset")]

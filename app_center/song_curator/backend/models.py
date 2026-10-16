import uuid
from django.conf import settings
from django.db import models
from modules.platform_api.tenancy import TenantOwnedModel


class CatalogGate(models.Model):
    """One global timestamp, containing no tenant or user data."""
    name = models.CharField(primary_key=True, max_length=30)
    next_at = models.FloatField(default=0)

    class Meta:
        db_table = 'song_curator_catalog_gate'


class MusicLibrary(TenantOwnedModel):
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    preferences = models.JSONField(default=dict)
    feedback = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'song_curator_library'
        constraints = [models.UniqueConstraint(fields=['organization', 'application', 'owner'], name='song_private_library')]


class Playlist(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(MusicLibrary, on_delete=models.CASCADE, related_name='playlists')
    name = models.CharField(max_length=120)
    tracks = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'song_curator_playlist'
        ordering = ['-updated_at', 'id']


class MusicOperation(TenantOwnedModel):
    library = models.ForeignKey(MusicLibrary, on_delete=models.CASCADE)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)

    class Meta:
        db_table = 'song_curator_operation'
        constraints = [models.UniqueConstraint(fields=['library', 'request_key'], name='song_operation_key')]


class MusicTask(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(MusicLibrary, on_delete=models.CASCADE, related_name='tasks')
    run = models.OneToOneField('execution.Run', null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=20)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default='queued')
    progress = models.CharField(max_length=240, blank=True)
    error = models.TextField(blank=True)
    cancel_requested = models.BooleanField(default=False)
    imported = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'song_curator_task'
        ordering = ['-created_at', 'id']
        constraints = [models.UniqueConstraint(fields=['library', 'request_key'], name='song_task_key')]


class MusicImage(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(MusicLibrary, on_delete=models.CASCADE, related_name='images')
    task = models.ForeignKey(MusicTask, null=True, on_delete=models.CASCADE, related_name='images')
    object_key = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'song_curator_image'
        constraints = [models.UniqueConstraint(fields=['library', 'request_key'], name='song_image_key')]

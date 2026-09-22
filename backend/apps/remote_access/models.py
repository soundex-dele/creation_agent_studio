"""Only connection metadata lives on the relay; business records stay local."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class LocalRemoteConfig(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    server_url = models.URLField(blank=True)
    computer_name = models.CharField(max_length=100, default="我的电脑")
    enabled = models.BooleanField(default=False)
    local_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    organization = models.ForeignKey("enterprise.Organization", null=True, on_delete=models.SET_NULL)
    device_id = models.UUIDField(null=True)
    # Fernet-encrypted using a key derived from the installation SECRET_KEY.
    credentials = models.TextField(blank=True)
    pairing_code = models.CharField(max_length=12, blank=True)
    pairing_expires_at = models.DateTimeField(null=True)
    bound_account = models.CharField(max_length=150, blank=True)
    revision = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, default="disabled")
    connector_seen_at = models.DateTimeField(null=True)


class RemoteDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64)
    pairing_hash = models.CharField(max_length=64, null=True, unique=True)
    pairing_expires_at = models.DateTimeField()
    confirmed = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True)
    session_id = models.CharField(max_length=32, blank=True)
    last_seen_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def online(self):
        return bool(self.confirmed and not self.revoked_at and self.session_id
                    and self.last_seen_at
                    and (timezone.now() - self.last_seen_at).total_seconds() < 60)

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

    class Meta:
        db_table = "animation_studio_assets"

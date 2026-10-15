import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class BrandEntry(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-updated_at", "id"]


class BrandProfile(BrandEntry):
    positioning = models.JSONField(default=dict, blank=True)
    voice = models.JSONField(default=dict, blank=True)
    visual = models.JSONField(default=dict, blank=True)

    class Meta(BrandEntry.Meta):
        db_table = "brand_library_profiles"
        indexes = [models.Index(fields=["organization", "application", "owner"], name="brand_profile_scope")]


class BrandProduct(BrandEntry):
    profile = models.ForeignKey(BrandProfile, related_name="products", on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    facts = models.JSONField(default=list, blank=True)
    source = models.TextField(blank=True)
    restrictions = models.TextField(blank=True)
    prohibited_claims = models.TextField(blank=True)

    class Meta(BrandEntry.Meta):
        db_table = "brand_library_products"


class BrandExample(BrandEntry):
    profile = models.ForeignKey(BrandProfile, related_name="examples", on_delete=models.CASCADE)
    platform = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    source_url = models.URLField(max_length=2000, blank=True)
    highlights = models.TextField(blank=True)

    class Meta(BrandEntry.Meta):
        db_table = "brand_library_examples"

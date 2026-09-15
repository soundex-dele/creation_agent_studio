"""Organization-scoped address books and contacts."""
import uuid

from django.conf import settings
from django.db import models

from modules.tenancy.models import TenantOwnedModel


class AddressBook(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.OneToOneField(
        "applications.Application",
        on_delete=models.CASCADE,
        related_name="address_book",
    )
    name = models.CharField(max_length=120, default="企业通讯录")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "address_books"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Contact(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    address_book = models.ForeignKey(
        AddressBook, on_delete=models.CASCADE, related_name="contacts"
    )
    name = models.CharField(max_length=120, db_index=True)
    company = models.CharField(max_length=160, blank=True, db_index=True)
    department = models.CharField(max_length=160, blank=True, db_index=True)
    job_title = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    avatar = models.URLField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_contacts",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contacts"
        ordering = ["name", "id"]
        indexes = [
            models.Index(
                fields=["organization", "address_book", "deleted_at"],
                name="contact_org_book_active_idx",
            )
        ]

    def __str__(self):
        return self.name


class ContactMethod(models.Model):
    class Kind(models.TextChoices):
        PHONE = "phone", "电话"
        EMAIL = "email", "邮箱"
        WECHAT = "wechat", "微信"
        OTHER = "other", "其他"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="methods"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    label = models.CharField(max_length=40, blank=True)
    value = models.CharField(max_length=255)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact_methods"
        ordering = ["kind", "-is_primary", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["contact", "kind", "value"],
                name="unique_contact_method_value",
            ),
            models.UniqueConstraint(
                fields=["contact", "kind"],
                condition=models.Q(is_primary=True),
                name="unique_primary_contact_method",
            ),
        ]

    def __str__(self):
        return f"{self.contact}: {self.value}"

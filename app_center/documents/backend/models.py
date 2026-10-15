import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


def empty_content():
    return {"type": "doc", "content": [{"type": "paragraph"}]}


class Document(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, default="未命名文档")
    content = models.JSONField(default=empty_content)
    plain_text = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "online_documents"
        ordering = ["-updated_at", "id"]
        indexes = [models.Index(fields=["organization", "application", "owner"], name="documents_scope")]


class DocumentGrant(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=[("viewer", "只读"), ("editor", "编辑")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "user"], name="document_user_grant")]


class DocumentSession(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.OneToOneField("conversations.Conversation", on_delete=models.CASCADE, related_name="document_session")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "user"], name="document_user_session")]

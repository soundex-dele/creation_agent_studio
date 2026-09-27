import uuid

from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class KitchenState(TenantOwnedModel):
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kitchen_assistant_state"
        constraints = [models.UniqueConstraint(
            fields=["organization", "application", "owner"], name="kitchen_private_state",
        )]


class KitchenRecord(TenantOwnedModel):
    state = models.ForeignKey(KitchenState, on_delete=models.CASCADE, related_name="history")
    record_id = models.CharField(max_length=200)
    data = models.JSONField(default=dict)
    finished_at = models.DateTimeField()
    recipe_names = models.TextField(default="", blank=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "kitchen_assistant_record"
        constraints = [models.UniqueConstraint(fields=["state", "record_id"], name="kitchen_record_identity")]
        indexes = [models.Index(fields=["state", "-finished_at", "id"], name="kitchen_record_page")]


class KitchenOperation(TenantOwnedModel):
    state = models.ForeignKey(KitchenState, on_delete=models.CASCADE)
    operation_id = models.UUIDField()

    class Meta:
        db_table = "kitchen_assistant_operation"
        constraints = [models.UniqueConstraint(fields=["state", "operation_id"], name="kitchen_operation_identity")]


class KitchenAITask(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.ForeignKey(KitchenState, on_delete=models.CASCADE, related_name="ai_tasks")
    run = models.OneToOneField("execution.Run", null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=20)
    instruction = models.TextField()
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="queued")
    error = models.TextField(blank=True)
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "kitchen_assistant_ai_task"
        ordering = ["-created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["state", "request_key"], name="kitchen_ai_request_key")]

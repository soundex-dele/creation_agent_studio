import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from modules.tenancy.models import TenantOwnedQuerySet


class Binding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("enterprise.Organization", on_delete=models.CASCADE)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    agent = models.ForeignKey("agents.Agent", null=True, blank=True, on_delete=models.SET_NULL)
    conversation = models.ForeignKey("conversations.Conversation", null=True, blank=True, on_delete=models.SET_NULL)
    # NULL permits multiple unbound records; uniqueness spans tenants.
    bot_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    peer_id = models.CharField(max_length=255, blank=True)
    credentials = models.TextField(blank=True)
    status = models.CharField(max_length=32, default="unbound")
    enabled = models.BooleanField(default=False)
    generation = models.UUIDField(default=uuid.uuid4)
    cursor = models.TextField(blank=True)
    login_id = models.UUIDField(null=True, blank=True)
    login_data = models.TextField(blank=True)
    login_expires_at = models.DateTimeField(null=True, blank=True)
    lease_owner = models.CharField(max_length=64, blank=True)
    lease_until = models.DateTimeField(default=timezone.now)
    next_poll_at = models.DateTimeField(default=timezone.now)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = "wechat_assistant_bindings"
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="wechat_binding_user_org")]


class IncomingMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("enterprise.Organization", on_delete=models.CASCADE)
    binding = models.ForeignKey(Binding, on_delete=models.CASCADE, related_name="incoming")
    generation = models.UUIDField()
    message_id = models.CharField(max_length=255)
    text = models.TextField(blank=True)
    context_token = models.TextField(blank=True)  # encrypted
    supported = models.BooleanField(default=True)
    state = models.CharField(max_length=24, default="pending")
    run = models.ForeignKey("execution.Run", null=True, blank=True, on_delete=models.PROTECT)
    conversation = models.ForeignKey("conversations.Conversation", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = "wechat_assistant_incoming"
        constraints = [models.UniqueConstraint(fields=["binding", "message_id"], name="wechat_incoming_unique")]
        ordering = ["created_at", "id"]


class OutgoingMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("enterprise.Organization", on_delete=models.CASCADE)
    incoming = models.ForeignKey(IncomingMessage, on_delete=models.CASCADE, related_name="replies")
    event_key = models.CharField(max_length=100)
    part = models.PositiveIntegerField(default=0)
    text = models.TextField()
    state = models.CharField(max_length=24, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        db_table = "wechat_assistant_outgoing"
        constraints = [models.UniqueConstraint(fields=["incoming", "event_key", "part"], name="wechat_outgoing_unique")]
        ordering = ["created_at", "part"]

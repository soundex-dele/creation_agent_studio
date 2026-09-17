import uuid

from django.conf import settings
from django.db import models


class Automation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        BLOCKED = "blocked", "Blocked"
        ARCHIVED = "archived", "Archived"

    class TriggerType(models.TextChoices):
        SCHEDULE = "schedule", "Schedule"
        WEBHOOK = "webhook", "Webhook"
        EVENT = "event", "Legacy event"

    class TargetType(models.TextChoices):
        APPLICATION = "application", "Application"
        WORKFLOW = "workflow", "Workflow"
        AGENT = "agent", "Legacy agent"

    class ScheduleKind(models.TextChoices):
        ONCE = "once", "Once"
        CRON = "cron", "Cron"

    organization = models.ForeignKey(
        "enterprise.Organization",
        on_delete=models.CASCADE,
        related_name="automation_triggers",
    )
    name = models.CharField(max_length=160)
    trigger_type = models.CharField(
        max_length=30, choices=TriggerType.choices, default=TriggerType.WEBHOOK
    )
    target_type = models.CharField(max_length=30, choices=TargetType.choices)
    # Kept in the original column for a lossless migration and old read clients.
    target_id = models.CharField(max_length=160)
    schedule = models.CharField(max_length=120, blank=True)
    event_name = models.CharField(max_length=160, blank=True)
    input_mapping = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_automations",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    schedule_kind = models.CharField(
        max_length=20, choices=ScheduleKind.choices, blank=True, default=""
    )
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    application = models.ForeignKey(
        "applications.Application",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="automations",
    )
    workflow = models.ForeignKey(
        "workflows.Workflow",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="automations",
    )
    default_input = models.JSONField(default=dict, blank=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    secret_digest = models.CharField(max_length=128, blank=True, default="")
    secret_prefix = models.CharField(max_length=16, blank=True, default="")
    secret_rotated_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True, default="")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "automation_triggers"
        ordering = ("-updated_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=~(
                    models.Q(application__isnull=False)
                    & models.Q(workflow__isnull=False)
                ),
                name="automation_at_most_one_target",
            )
        ]
        indexes = [
            models.Index(
                fields=("status", "next_run_at"), name="automation_due_idx"
            )
        ]

    def __str__(self):
        return self.name


class AutomationInvocation(models.Model):
    class Source(models.TextChoices):
        SCHEDULE = "schedule", "Schedule"
        WEBHOOK = "webhook", "Webhook"
        MANUAL = "manual", "Manual"

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        DISPATCHED = "dispatched", "Dispatched"
        FAILED = "failed", "Failed"
        SKIPPED_CAPACITY = "skipped_capacity", "Skipped: capacity"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "enterprise.Organization",
        on_delete=models.CASCADE,
        related_name="automation_invocations",
    )
    automation = models.ForeignKey(
        Automation, on_delete=models.CASCADE, related_name="invocations"
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    dedup_key = models.CharField(max_length=200)
    request_fingerprint = models.CharField(max_length=64, blank=True, default="")
    outcome = models.CharField(
        max_length=30, choices=Outcome.choices, default=Outcome.PENDING, db_index=True
    )
    run = models.OneToOneField(
        "execution.Run",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="automation_invocation",
    )
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "automation_invocations"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("automation", "dedup_key"),
                name="unique_automation_invocation_dedup",
            )
        ]

import uuid

from django.conf import settings
from django.db import models

from modules.tenancy.models import TenantOwnedModel, TenantOwnedQuerySet


class RunQuerySet(TenantOwnedQuerySet):
    def queued_for_pool(self, worker_pool, executor_keys=None):
        queryset = self.filter(
            status=Run.Status.QUEUED,
            executor_kind=worker_pool,
            current_attempt__isnull=True,
        )
        if executor_keys is not None:
            queryset = queryset.filter(executor_key__in=executor_keys)
        return queryset


class Run(TenantOwnedModel):
    class ExecutorKind(models.TextChoices):
        AGENT = "agent", "Agent"
        MEDIA = "media", "Media"
        WORKFLOW = "workflow", "Workflow"
        EVALUATION = "evaluation", "Evaluation"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        WAITING_INPUT = "waiting_input", "Waiting for input"
        CANCELLING = "cancelling", "Cancelling"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class InputKind(models.TextChoices):
        ANSWER = "answer", "Answer"
        PERMISSION = "permission", "Permission"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="execution_runs",
    )
    executor_kind = models.CharField(
        max_length=20,
        choices=ExecutorKind.choices,
        db_index=True,
    )
    executor_key = models.CharField(max_length=100, blank=True, default="", db_index=True)
    source_type = models.CharField(max_length=80, db_index=True)
    source_id = models.CharField(max_length=160, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    priority = models.SmallIntegerField(default=0, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    version = models.PositiveBigIntegerField(default=0)
    next_event_sequence = models.PositiveBigIntegerField(default=0)
    next_lease_epoch = models.PositiveBigIntegerField(default=0)
    retry_safe = models.BooleanField(default=True)
    definition_snapshot = models.JSONField(default=dict)
    input = models.JSONField(default=dict)
    output_summary = models.JSONField(default=dict, blank=True)
    current_attempt = models.ForeignKey(
        "RunAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    pending_input_request_id = models.UUIDField(null=True, blank=True)
    pending_input_kind = models.CharField(
        max_length=20,
        choices=InputKind.choices,
        blank=True,
        default="",
    )
    pending_input_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = RunQuerySet.as_manager()

    class Meta:
        db_table = "runs"
        ordering = ("-priority", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                check=models.Q(max_attempts__gte=1),
                name="run_max_attempts_at_least_one",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(
                        status="waiting_input",
                        pending_input_request_id__isnull=False,
                        pending_input_kind__in=("answer", "permission"),
                        pending_input_expires_at__isnull=False,
                    )
                    | (
                        ~models.Q(status="waiting_input")
                        & models.Q(pending_input_request_id__isnull=True)
                        & models.Q(pending_input_kind="")
                        & models.Q(pending_input_expires_at__isnull=True)
                    )
                ),
                name="run_pending_input_consistent",
            ),
        ]
        indexes = [
            models.Index(
                fields=("executor_kind", "status", "-priority", "created_at"),
                name="run_claim_idx",
            )
        ]


class RunAttempt(models.Model):
    class Status(models.TextChoices):
        CLAIMED = "claimed", "Claimed"
        RUNNING = "running", "Running"
        SUSPENDED = "suspended", "Suspended"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        INTERRUPTED = "interrupted", "Interrupted"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="attempts")
    attempt_no = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CLAIMED,
        db_index=True,
    )
    worker_pool = models.CharField(max_length=40, db_index=True)
    checkpoint_artifact = models.ForeignKey(
        "RunArtifact",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    error_code = models.CharField(max_length=100, blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "run_attempts"
        ordering = ("run_id", "attempt_no")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "attempt_no"),
                name="unique_run_attempt_number",
            ),
            models.UniqueConstraint(
                fields=("run",),
                condition=models.Q(finished_at__isnull=True),
                name="one_active_attempt_per_run",
            ),
        ]


class RunLease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.OneToOneField(
        RunAttempt,
        on_delete=models.CASCADE,
        related_name="lease",
    )
    worker_id = models.CharField(max_length=160, db_index=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    epoch = models.PositiveBigIntegerField()
    acquired_at = models.DateTimeField(auto_now_add=True)
    heartbeat_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "run_leases"
        constraints = [
            models.UniqueConstraint(
                fields=("attempt", "epoch"),
                name="unique_attempt_lease_epoch",
            )
        ]


class RunEvent(TenantOwnedModel):
    id = models.BigAutoField(primary_key=True)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    attempt = models.ForeignKey(
        RunAttempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    sequence = models.PositiveBigIntegerField()
    type = models.CharField(max_length=100, db_index=True)
    schema_version = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "run_events"
        ordering = ("run_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "sequence"),
                name="unique_run_event_sequence",
            )
        ]
        indexes = [
            models.Index(
                fields=("run", "sequence"),
                name="run_event_cursor_idx",
            )
        ]


class RunEventSnapshot(TenantOwnedModel):
    """Latest durable client projection preceding compacted Run events."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.OneToOneField(
        Run,
        on_delete=models.CASCADE,
        related_name="event_snapshot",
    )
    through_sequence = models.PositiveBigIntegerField()
    schema_version = models.PositiveSmallIntegerField(default=1)
    projection = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "run_event_snapshots"
        constraints = [
            models.CheckConstraint(
                check=models.Q(through_sequence__gte=1),
                name="run_snapshot_sequence_positive",
            )
        ]


class RunCommand(TenantOwnedModel):
    class Type(models.TextChoices):
        ANSWER = "answer", "Answer"
        GRANT_PERMISSION = "grant_permission", "Grant permission"
        DENY_PERMISSION = "deny_permission", "Deny permission"
        CANCEL = "cancel", "Cancel"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="commands")
    type = models.CharField(max_length=30, choices=Type.choices)
    input_request_id = models.UUIDField(null=True, blank=True)
    expected_run_version = models.PositiveBigIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="run_commands",
    )
    idempotency_key = models.CharField(max_length=160)
    request_fingerprint = models.CharField(max_length=64)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "run_commands"
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "created_by", "type", "idempotency_key"),
                name="unique_run_command_idempotency",
            )
        ]


class RunArtifact(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="artifacts")
    attempt = models.ForeignKey(
        RunAttempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artifacts",
    )
    kind = models.CharField(max_length=50, db_index=True)
    object_key = models.CharField(max_length=500)
    content_hash = models.CharField(max_length=64, db_index=True)
    mime_type = models.CharField(max_length=160)
    size = models.PositiveBigIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "run_artifacts"
        constraints = [
            models.UniqueConstraint(
                fields=("run", "object_key", "content_hash"),
                name="unique_run_artifact_content",
            )
        ]


class IdempotencyRecord(TenantOwnedModel):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
    )
    operation = models.CharField(max_length=160)
    key = models.CharField(max_length=160)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "actor", "operation", "key"),
                name="unique_idempotency_scope",
            )
        ]

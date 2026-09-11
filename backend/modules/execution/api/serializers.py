from rest_framework import serializers

from modules.catalog.models import DeploymentEnvironment
from modules.execution.models import (
    Run,
    RunArtifact,
    RunAttempt,
    RunCommand,
    RunEvent,
    RunEventSnapshot,
)


class RunSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    owner_id = serializers.ReadOnlyField()
    current_attempt_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Run
        fields = (
            "id",
            "organization_id",
            "owner_id",
            "executor_kind",
            "executor_key",
            "source_type",
            "source_id",
            "status",
            "priority",
            "attempt_count",
            "max_attempts",
            "version",
            "next_event_sequence",
            "retry_safe",
            "definition_snapshot",
            "input",
            "output_summary",
            "current_attempt_id",
            "pending_input_request_id",
            "pending_input_kind",
            "pending_input_expires_at",
            "error_code",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
        )


class RunEventSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(read_only=True)
    attempt_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = RunEvent
        fields = (
            "schema_version",
            "run_id",
            "attempt_id",
            "sequence",
            "type",
            "payload",
            "created_at",
        )


class RunAttemptSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(read_only=True)
    checkpoint_artifact_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = RunAttempt
        fields = (
            "id",
            "run_id",
            "attempt_no",
            "status",
            "worker_pool",
            "checkpoint_artifact_id",
            "error_code",
            "started_at",
            "finished_at",
        )


class RunArtifactSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(read_only=True)
    attempt_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = RunArtifact
        fields = (
            "id",
            "run_id",
            "attempt_id",
            "kind",
            "content_hash",
            "mime_type",
            "size",
            "metadata",
            "created_at",
        )


class RunEventSnapshotSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = RunEventSnapshot
        fields = (
            "schema_version",
            "run_id",
            "through_sequence",
            "projection",
            "created_at",
            "updated_at",
        )


class SubmitRunCommandSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=RunCommand.Type.choices)
    idempotency_key = serializers.CharField(min_length=1, max_length=160)
    input_request_id = serializers.UUIDField(required=False, allow_null=True)
    expected_run_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
    )
    payload = serializers.JSONField(required=False, default=dict)


class RunCommandSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(read_only=True)
    created_by_id = serializers.ReadOnlyField()

    class Meta:
        model = RunCommand
        fields = (
            "id",
            "run_id",
            "type",
            "input_request_id",
            "expected_run_version",
            "payload",
            "created_by_id",
            "idempotency_key",
            "result",
            "created_at",
            "consumed_at",
        )


class StartApplicationRunSerializer(serializers.Serializer):
    environment = serializers.ChoiceField(
        choices=DeploymentEnvironment.choices,
        default=DeploymentEnvironment.PRODUCTION,
    )
    input = serializers.JSONField()
    priority = serializers.IntegerField(default=0, min_value=-100, max_value=100)

    def validate_input(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("input must be a JSON object")
        return value

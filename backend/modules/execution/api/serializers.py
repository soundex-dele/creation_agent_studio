from rest_framework import serializers

from modules.execution.models import (
    Run,
    RunArtifact,
    RunAttempt,
    RunCommand,
    RunEvent,
    RunEventSnapshot,
)
from .permissions import can_delete_run


class RunSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    owner_id = serializers.ReadOnlyField()
    current_attempt_id = serializers.UUIDField(read_only=True, allow_null=True)
    parent_id = serializers.UUIDField(read_only=True, allow_null=True)
    can_delete = serializers.SerializerMethodField()
    task_type = serializers.SerializerMethodField()
    task_title = serializers.SerializerMethodField()
    trigger_type = serializers.SerializerMethodField()
    automation_id = serializers.SerializerMethodField()
    workflow_id = serializers.SerializerMethodField()
    application_id = serializers.SerializerMethodField()
    conversation_id = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = (
            "id",
            "organization_id",
            "owner_id",
            "parent_id",
            "node_key",
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
            "can_delete",
            "task_type",
            "task_title",
            "trigger_type",
            "automation_id",
            "workflow_id",
            "application_id",
            "conversation_id",
        )

    def get_can_delete(self, obj):
        return can_delete_run(obj, self.context.get("request"))

    @staticmethod
    def _automation_invocation(obj):
        try:
            return obj.automation_invocation
        except AttributeError:
            return None

    def get_task_type(self, obj):
        if self._automation_invocation(obj) is not None:
            return "automation"
        if obj.source_type == "workflow_step":
            return "conversation" if self._conversation_id(obj) else "execution"
        return {
            "supervisor": "delegate",
            "supervisor_task": "delegate",
            "application": "execution",
        }.get(obj.source_type, obj.source_type)

    def get_task_title(self, obj):
        invocation = self._automation_invocation(obj)
        if invocation is not None:
            return invocation.automation.name
        conversation = self._conversation_metadata(obj)
        if self._conversation_id(obj) and conversation and conversation.get("title"):
            return str(conversation["title"])
        snapshot = obj.definition_snapshot or {}
        for key in (
            "workflow_name", "application_name", "supervisor_name",
            "conversation_title", "workflow_step_name", "agent_name",
        ):
            value = snapshot.get(key)
            if value:
                return str(value)
        return {
            "application": "执行任务",
            "execution": "执行任务",
            "workflow": "工作流任务",
            "conversation": "对话任务",
            "supervisor": "AI 分身任务",
            "agent": "智能体任务",
            "evaluation": "评测任务",
        }.get(obj.source_type, "任务")

    def get_trigger_type(self, obj):
        invocation = self._automation_invocation(obj)
        if invocation is not None:
            return invocation.source
        return "parent" if obj.parent_id else "manual"

    def get_automation_id(self, obj) -> int | None:
        invocation = self._automation_invocation(obj)
        return invocation.automation_id if invocation is not None else None

    @staticmethod
    def _conversation_id(obj) -> str | None:
        if obj.source_type == "conversation" and obj.source_id:
            return str(obj.source_id)
        value = (obj.definition_snapshot or {}).get("conversation_id")
        return str(value) if value else None

    def _conversation_metadata(self, obj):
        conversation_id = self._conversation_id(obj)
        if conversation_id is None:
            return None
        cache = self.context.setdefault("run_conversation_metadata", {})
        if conversation_id not in cache:
            from apps.conversations.models import Conversation

            cache[conversation_id] = Conversation.objects.filter(
                organization_id=obj.organization_id,
                pk=conversation_id,
            ).values("title", "chat_application_id").first()
        return cache[conversation_id]

    def get_workflow_id(self, obj) -> str | None:
        if obj.source_type == "workflow" and obj.source_id:
            return str(obj.source_id)
        value = (obj.definition_snapshot or {}).get("workflow_id")
        return str(value) if value else None

    def get_application_id(self, obj) -> str | None:
        if obj.source_type == "application" and obj.source_id:
            return str(obj.source_id)
        value = (obj.definition_snapshot or {}).get("application_id")
        if value:
            return str(value)
        conversation = self._conversation_metadata(obj)
        if conversation and conversation.get("chat_application_id"):
            return str(conversation["chat_application_id"])
        return None

    def get_conversation_id(self, obj) -> str | None:
        return self._conversation_id(obj)


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
    input = serializers.JSONField()
    priority = serializers.IntegerField(default=0, min_value=-100, max_value=100)

    def validate_input(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("input must be a JSON object")
        return value


class StartAgentRunSerializer(serializers.Serializer):
    input = serializers.JSONField()
    priority = serializers.IntegerField(default=0, min_value=-100, max_value=100)

    def validate_input(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("input must be a JSON object")
        return value

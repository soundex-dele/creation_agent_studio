from django.db.models import Q
from rest_framework import serializers

from apps.applications.models import Application
from apps.workflows.models import Workflow
from core.resource_access import accessible_resources

from .models import Automation, AutomationInvocation
from .scheduling import ScheduleValidationError, preview_schedule


class AutomationSerializer(serializers.ModelSerializer):
    target_name = serializers.SerializerMethodField()
    webhook_url = serializers.SerializerMethodField()
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True
    )
    last_invocation = serializers.SerializerMethodField()

    class Meta:
        model = Automation
        fields = (
            "id", "name", "description", "status", "trigger_type",
            "target_type", "target_id", "target_name", "default_input",
            "schedule_kind", "timezone", "run_at", "schedule",
            "next_run_at", "last_scheduled_at", "last_triggered_at",
            "public_id", "webhook_url", "secret_prefix", "secret_rotated_at",
            "blocked_reason", "created_by", "created_by_username",
            "created_at", "updated_at", "last_invocation",
        )
        read_only_fields = fields

    def get_target_name(self, obj):
        target = obj.application or obj.workflow
        return target.name if target else "不可用的旧版目标"

    def get_webhook_url(self, obj):
        if obj.trigger_type != Automation.TriggerType.WEBHOOK:
            return ""
        return f"/api/v1/hooks/automations/{obj.public_id}"

    def get_last_invocation(self, obj):
        invocation = obj.invocations.select_related("run").order_by("-created_at").first()
        return AutomationInvocationSerializer(invocation).data if invocation else None


class AutomationWriteSerializer(serializers.ModelSerializer):
    target_id = serializers.CharField()

    class Meta:
        model = Automation
        fields = (
            "name", "description", "trigger_type", "target_type", "target_id",
            "default_input", "schedule_kind", "timezone", "run_at", "schedule",
        )

    def validate_default_input(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("默认参数必须是 JSON 对象。")
        return value

    def validate(self, attrs):
        instance = self.instance
        trigger_type = attrs.get(
            "trigger_type", getattr(instance, "trigger_type", "")
        )
        if trigger_type not in (
            Automation.TriggerType.SCHEDULE, Automation.TriggerType.WEBHOOK
        ):
            raise serializers.ValidationError({"trigger_type": "仅支持定时或 Webhook。"})
        target_type = attrs.get("target_type", getattr(instance, "target_type", ""))
        if target_type not in (
            Automation.TargetType.APPLICATION, Automation.TargetType.WORKFLOW
        ):
            raise serializers.ValidationError({"target_type": "仅支持应用或工作流。"})

        organization = self.context["organization"]
        target_id = attrs.get("target_id", getattr(instance, "target_id", ""))
        if target_type == Automation.TargetType.APPLICATION:
            try:
                target = accessible_resources(Application.objects.filter(
                    Q(organization=organization) | Q(organization__isnull=True),
                    pk=target_id,
                    is_active=True,
                ), self.context["request"].user, operation="run").first()
            except (TypeError, ValueError):
                target = None
            if target is None:
                raise serializers.ValidationError({"target_id": "目标应用不存在。"})
            attrs["application"] = target
            attrs["workflow"] = None
        else:
            target = Workflow.objects.filter(
                pk=target_id,
                organization=organization,
                execution_mode=Workflow.ExecutionMode.AUTOMATIC,
            ).first()
            if target is None:
                raise serializers.ValidationError({"target_id": "自动工作流不存在。"})
            attrs["workflow"] = target
            attrs["application"] = None

        if trigger_type == Automation.TriggerType.SCHEDULE:
            kind = attrs.get("schedule_kind", getattr(instance, "schedule_kind", ""))
            expression = attrs.get("schedule", getattr(instance, "schedule", ""))
            run_at = attrs.get("run_at", getattr(instance, "run_at", None))
            timezone_name = attrs.get(
                "timezone", getattr(instance, "timezone", "Asia/Shanghai")
            )
            try:
                preview_schedule(
                    kind=kind,
                    expression=expression,
                    run_at=run_at,
                    timezone_name=timezone_name,
                    count=1,
                )
            except ScheduleValidationError as exc:
                raise serializers.ValidationError({"schedule": str(exc)}) from exc
        return attrs

    def create(self, validated_data):
        validated_data["input_mapping"] = dict(validated_data.get("default_input") or {})
        validated_data["is_active"] = False
        validated_data["status"] = Automation.Status.PAUSED
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["input_mapping"] = dict(
            validated_data.get("default_input", instance.default_input) or {}
        )
        automation = super().update(instance, validated_data)
        if automation.status == Automation.Status.ACTIVE:
            automation.status = Automation.Status.PAUSED
            automation.is_active = False
            automation.next_run_at = None
            automation.save(update_fields=(
                "status", "is_active", "next_run_at", "updated_at",
            ))
        return automation


class AutomationInvocationSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(read_only=True, allow_null=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = AutomationInvocation
        fields = (
            "id", "source", "scheduled_for", "outcome", "status", "run_id",
            "error", "created_at",
        )

    def get_status(self, obj):
        return obj.run.status if obj.run_id else obj.outcome


class SchedulePreviewSerializer(serializers.Serializer):
    schedule_kind = serializers.ChoiceField(choices=Automation.ScheduleKind.choices)
    timezone = serializers.CharField(max_length=64)
    schedule = serializers.CharField(required=False, allow_blank=True, default="")
    run_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        try:
            attrs["next_runs"] = preview_schedule(
                kind=attrs["schedule_kind"],
                expression=attrs.get("schedule", ""),
                run_at=attrs.get("run_at"),
                timezone_name=attrs["timezone"],
            )
        except ScheduleValidationError as exc:
            raise serializers.ValidationError({"schedule": str(exc)}) from exc
        return attrs


class AutomationTargetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=("application", "workflow"))
    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)


class SchedulePreviewResponseSerializer(serializers.Serializer):
    next_runs = serializers.ListField(child=serializers.DateTimeField())

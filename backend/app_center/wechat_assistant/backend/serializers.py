from rest_framework import serializers
from .models import Binding, IncomingMessage, OutgoingMessage
from .protocol import unseal
from .services import is_busy


class BindingSerializer(serializers.ModelSerializer):
    agent_id = serializers.IntegerField(read_only=True, allow_null=True)
    conversation_id = serializers.IntegerField(read_only=True, allow_null=True)
    busy = serializers.SerializerMethodField()
    qr_content = serializers.SerializerMethodField()

    class Meta:
        model = Binding
        fields = ["id", "status", "enabled", "agent_id", "conversation_id", "busy", "login_id", "login_expires_at", "qr_content", "heartbeat_at", "received_at", "sent_at", "last_error"]
        read_only_fields = fields

    def get_busy(self, obj):
        return is_busy(obj)

    def get_qr_content(self, obj):
        if obj.status in ("wait", "scaned", "need_verifycode"):
            return unseal(obj.login_data).get("display", "")
        return ""


class ConfigurationSerializer(serializers.Serializer):
    agent_id = serializers.IntegerField(min_value=1)


class VerifySerializer(serializers.Serializer):
    login_id = serializers.UUIDField()
    code = serializers.RegexField(r"^[0-9]{4,12}$")


class AgentOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()


class ReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = OutgoingMessage
        fields = ["id", "state", "attempts", "last_error"]


class TaskSerializer(serializers.ModelSerializer):
    replies = ReplySerializer(many=True, read_only=True)
    run_id = serializers.UUIDField(read_only=True, allow_null=True)
    conversation_id = serializers.IntegerField(read_only=True, allow_null=True)
    run_status = serializers.CharField(source="run.status", read_only=True, default="")

    class Meta:
        model = IncomingMessage
        fields = ["id", "text", "state", "run_id", "run_status", "conversation_id", "created_at", "replies"]

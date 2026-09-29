from rest_framework import serializers
from drf_yasg.utils import swagger_serializer_method
from .models import Account, Task, ScriptVersion
from .provider import source_url, work_web_url


class AccountInput(serializers.Serializer):
    class Meta:
        ref_name = "DouyinAccountInput"

    source = serializers.CharField(max_length=4000)
    count = serializers.ChoiceField(choices=[20, 50, 100], default=50)
    group = serializers.CharField(max_length=100, allow_blank=True, default="")
    notes = serializers.CharField(max_length=5000, allow_blank=True, default="")

    def validate_source(self, value):
        try:
            return source_url(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        ref_name = "DouyinAccount"
        fields = ["id", "source_url", "platform_id", "name", "group", "notes", "profile", "updated_at"]
        read_only_fields = ["id", "source_url", "platform_id", "name", "profile", "updated_at"]
        extra_kwargs = {"notes": {"max_length": 5000}}


class TaskInput(serializers.Serializer):
    class Meta:
        ref_name = "DouyinTaskInput"

    kind = serializers.ChoiceField(choices=["collect", "account", "breakdown", "topics", "script"])
    count = serializers.ChoiceField(choices=[20, 50, 100], default=50)
    work_id = serializers.UUIDField(required=False)
    batch_id = serializers.UUIDField(required=False)
    source_task_id = serializers.UUIDField(required=False)
    topic_index = serializers.IntegerField(min_value=0, max_value=2, default=0)
    positioning = serializers.CharField(max_length=2000, allow_blank=True, default="")
    audience = serializers.CharField(max_length=2000, allow_blank=True, default="")
    theme = serializers.CharField(max_length=2000, allow_blank=True, default="")
    duration = serializers.IntegerField(min_value=15, max_value=600, default=60)
    conditions = serializers.CharField(max_length=3000, allow_blank=True, default="")
    brand_profile_id = serializers.UUIDField(required=False, allow_null=True)


class TaskSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    work_id = serializers.UUIDField(read_only=True, allow_null=True)
    run_id = serializers.UUIDField(read_only=True, allow_null=True)
    output = serializers.SerializerMethodField()
    sources = serializers.SerializerMethodField()

    class Meta:
        model = Task
        ref_name = "DouyinTask"
        fields = ["id", "kind", "work_id", "run_id", "status", "stage", "error", "progress", "output", "sources", "created_at"]

    def get_status(self, obj) -> str:
        return obj.run.status if obj.run else "failed"

    @swagger_serializer_method(serializer_or_field=serializers.JSONField())
    def get_output(self, obj):
        value = dict(obj.output)
        if "frames" in value:
            value["frames"] = [{"id": f["id"], "time": f["time"]} for f in value["frames"]]
        return value

    @swagger_serializer_method(serializer_or_field=serializers.ListField(child=serializers.JSONField()))
    def get_sources(self, obj):
        return [{**item, "url": work_web_url(item)} for item in obj.input.get("evidence", [])]


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScriptVersion
        ref_name = "DouyinScriptVersion"
        fields = ["id", "revision", "content", "created_at"]


class ScriptEdit(serializers.Serializer):
    class Meta:
        ref_name = "DouyinScriptEdit"

    revision = serializers.IntegerField(min_value=1)
    content = serializers.JSONField()

    def validate_content(self, value):
        from .analysis import validate_script
        try:
            return validate_script(value)
        except (ValueError, AttributeError) as exc:
            raise serializers.ValidationError(str(exc))


class AccountPage(serializers.Serializer):
    count = serializers.IntegerField()
    results = AccountSerializer(many=True)
    class Meta:
        ref_name = "DouyinAccountPage"


class TaskPage(serializers.Serializer):
    count = serializers.IntegerField()
    results = TaskSerializer(many=True)
    class Meta:
        ref_name = "DouyinTaskPage"


class ConnectionSerializer(serializers.Serializer):
    connected = serializers.BooleanField()
    message = serializers.CharField()
    code = serializers.CharField(required=False)
    class Meta:
        ref_name = "DouyinConnection"


class WorkResultSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.JSONField())
    sample_size = serializers.IntegerField()
    median_likes = serializers.FloatField(allow_null=True)
    explanation = serializers.CharField()
    batch = TaskSerializer(allow_null=True)
    class Meta:
        ref_name = "DouyinWorks"


class UploadInput(serializers.Serializer):
    video = serializers.FileField()
    class Meta:
        ref_name = "DouyinUpload"


class AccountCreated(AccountSerializer):
    task = TaskSerializer()
    reused = serializers.BooleanField()
    class Meta(AccountSerializer.Meta):
        ref_name = "DouyinAccountCreated"
        fields = AccountSerializer.Meta.fields + ["task", "reused"]


class CollectorConfigInput(serializers.Serializer):
    class Meta:
        ref_name = "DouyinCollectorConfigInput"

    user_agent = serializers.CharField(max_length=2000)
    cookies = serializers.CharField(max_length=64000, required=False, allow_blank=True, write_only=True, trim_whitespace=False)
    screen = serializers.RegexField(r"^[1-9]\d{1,4}x[1-9]\d{1,4}$", default="1920x1080", max_length=20)
    language = serializers.RegexField(r"^[a-zA-Z-]{2,50}$", default="zh-CN", max_length=50)
    timezone = serializers.CharField(default="Asia/Shanghai", max_length=100)

    def validate_user_agent(self, value):
        if "\n" in value or "\r" in value:
            raise serializers.ValidationError("User-Agent 不能包含换行。")
        return value

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("请输入有效时区，如 Asia/Shanghai。")
        return value


class CollectorConfigOutput(serializers.Serializer):
    class Meta:
        ref_name = "DouyinCollectorConfig"

    configured = serializers.BooleanField()
    user_agent = serializers.CharField(allow_blank=True)
    has_cookies = serializers.BooleanField()
    screen = serializers.CharField()
    language = serializers.CharField()
    timezone = serializers.CharField()
    updated_at = serializers.DateTimeField(allow_null=True)

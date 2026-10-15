from rest_framework import serializers
from drf_yasg.utils import swagger_serializer_method
from .models import Account, Task, ScriptVersion
from .provider import source_url, work_web_url
from .creation_formats import DEFAULT_FORMAT, FORMAT_LABELS


class AccountInput(serializers.Serializer):
    class Meta:
        ref_name = "DouyinAccountInput"

    source = serializers.CharField(max_length=4000)
    is_owned = serializers.BooleanField(default=False)
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
        fields = ["id", "source_url", "platform_id", "name", "group", "notes", "is_owned", "profile", "updated_at"]
        read_only_fields = ["id", "source_url", "platform_id", "name", "profile", "updated_at"]
        extra_kwargs = {"notes": {"max_length": 5000}}


class TaskInput(serializers.Serializer):
    class Meta:
        ref_name = "DouyinTaskInput"

    kind = serializers.ChoiceField(choices=["collect", "account", "breakdown", "topics", "script", "transcribe", "rewrite"])
    force = serializers.BooleanField(required=False)
    source_text = serializers.CharField(max_length=20000, required=False)
    rewrite_requirements = serializers.CharField(max_length=3000, allow_blank=True, required=False)
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
    production_format = serializers.ChoiceField(choices=list(FORMAT_LABELS.items()), default=DEFAULT_FORMAT)
    brand_profile_id = serializers.UUIDField(required=False, allow_null=True)
    profile_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["kind"] == "transcribe":
            attrs.setdefault("force", False)
        if attrs["kind"] in ("transcribe", "rewrite") and not attrs.get("work_id"):
            raise serializers.ValidationError({"work_id": "请选择作品。"})
        if attrs["kind"] == "rewrite":
            attrs.setdefault("rewrite_requirements", "")
            for field in ("source_text",):
                if not attrs.get(field):
                    raise serializers.ValidationError({field: "请先获取并校正原文。"})
        if attrs["kind"] == "topics" and attrs["production_format"] == "animation" and attrs["duration"] > 120:
            raise serializers.ValidationError({"duration": "动画演示最长支持120秒，请调整目标时长。"})
        return attrs


class TaskSerializer(serializers.ModelSerializer):
    copy_context = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    work_id = serializers.UUIDField(read_only=True, allow_null=True)
    run_id = serializers.UUIDField(read_only=True, allow_null=True)
    output = serializers.SerializerMethodField()
    sources = serializers.SerializerMethodField()

    class Meta:
        model = Task
        ref_name = "DouyinTask"
        fields = ["id", "account_id", "kind", "work_id", "run_id", "status", "stage", "error", "progress", "output", "sources", "copy_context", "created_at"]

    def get_status(self, obj) -> str:
        return obj.run.status if obj.run else "failed"

    @swagger_serializer_method(serializer_or_field=serializers.JSONField())
    def get_copy_context(self, obj):
        if obj.kind not in ("transcribe", "rewrite"):
            return None
        return {"work_kind": obj.input.get("work_kind", "video"),
                **{key: obj.input.get(key, "") for key in
                   ("work_title", "work_description", "source_task_id", "source_text", "rewrite_requirements", "theme")}}

    @swagger_serializer_method(serializer_or_field=serializers.JSONField())
    def get_output(self, obj):
        value = dict(obj.output)
        if obj.input.get('reference', {}).get('cases'):
            value['case_references'] = obj.input['reference']['cases']
        if obj.kind == 'knowledge_extract':
            value['source_task_id'] = obj.input.get('source_task_id')
            from .models import CreationKnowledgeCard
            value['saved_candidate_ids'] = list(CreationKnowledgeCard.objects.filter(
                extraction_key=obj.pk, organization_id=obj.organization_id, application_id=obj.application_id,
                owner_id=obj.owner_id).values_list('candidate_id', flat=True))
        if obj.kind in ('radar_hotlist', 'radar_search', 'radar_topics'):
            value['radar_request'] = {key: obj.input[key] for key in
                ('kind', 'keyword', 'source_task_id', 'source_ids', 'target_account_id') if key in obj.input}
        if obj.input.get('reference', {}).get('knowledge'):
            value['knowledge_cards'] = obj.input['reference']['knowledge']
        if obj.input.get('reference', {}).get('organization_knowledge'):
            value['organization_knowledge'] = obj.input['reference']['organization_knowledge']
        brief = obj.input.get('brief', {})
        if brief.get('target_account_id'):
            value['creation_context'] = {k: brief[k] for k in ['target_account_id', 'account_name', 'voice_version_number'] if k in brief}
        if obj.kind == 'variants' and obj.input.get('source_version_id'):
            source = ScriptVersion.objects.filter(pk=obj.input['source_version_id'], task__owner_id=obj.owner_id,
                task__application_id=obj.application_id, task__organization_id=obj.organization_id).first()
            if source:
                value['source_task_id'] = str(source.task_id)
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
        from .analysis import validate_script, validate_rewrite
        try:
            if self.context.get('kind') == 'article':
                from .article import validate_article
                return validate_article(value)
            if self.context.get('kind') == 'variants':
                from .research_runtime import validate_variants
                return validate_variants(value)
            return (validate_rewrite if self.context.get("kind") == "rewrite" else validate_script)(value)
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
    cookies = serializers.CharField(allow_blank=True)
    screen = serializers.CharField()
    language = serializers.CharField()
    timezone = serializers.CharField()
    updated_at = serializers.DateTimeField(allow_null=True)

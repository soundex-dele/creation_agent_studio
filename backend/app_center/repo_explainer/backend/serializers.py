from rest_framework import serializers


class ProjectInput(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    archived = serializers.BooleanField(required=False)


class ImportInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['github', 'zip', 'local'])
    url = serializers.CharField(required=False, max_length=1000)
    ref = serializers.CharField(required=False, allow_blank=True, max_length=200)
    path = serializers.CharField(required=False, max_length=2000)
    file = serializers.FileField(required=False)

    def validate(self, values):
        field = {'github': 'url', 'zip': 'file', 'local': 'path'}[values['kind']]
        if not values.get(field):
            raise serializers.ValidationError({field: '请提供仓库来源。'})
        return values


class TaskInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['analyze', 'write'])
    snapshot_id = serializers.UUIDField(required=False)
    analysis_id = serializers.UUIDField(required=False)
    feature_ids = serializers.ListField(child=serializers.CharField(max_length=30), required=False, max_length=60)
    angle = serializers.ChoiceField(choices=['overview', 'feature', 'tutorial'], default='overview')
    output = serializers.ChoiceField(choices=['both', 'video', 'article'], default='both')
    audience = serializers.CharField(max_length=1000, default='有 AI 使用需求的普通用户')
    style = serializers.CharField(max_length=2000, default='清晰、具体、口语自然')
    duration = serializers.IntegerField(min_value=5, max_value=600, default=60)
    aspect = serializers.ChoiceField(choices=['16:9', '9:16', '1:1'], default='16:9')


class SaveInput(serializers.Serializer):
    revision = serializers.IntegerField(min_value=1)
    document = serializers.DictField()


class HandoffInput(serializers.Serializer):
    version_id = serializers.UUIDField()
    target_id = serializers.IntegerField(min_value=1)


class HandoffSaveInput(serializers.Serializer):
    revision = serializers.IntegerField(min_value=1)
    draft = serializers.DictField(required=False)
    conversation_id = serializers.IntegerField(min_value=1, required=False)

from rest_framework import serializers


class SendSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000, allow_blank=True, default='', trim_whitespace=False)
    request_key = serializers.CharField(max_length=160)
    attachments = serializers.ListField(child=serializers.UUIDField(), max_length=9, default=list)

    def validate(self, attrs):
        if not attrs['text'].strip() and not attrs['attachments']:
            raise serializers.ValidationError('请填写消息或选择附件。')
        if len(set(attrs['attachments'])) != len(attrs['attachments']):
            raise serializers.ValidationError('附件不能重复。')
        return attrs


class CreateRoomSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['direct', 'group'])
    name = serializers.CharField(max_length=100, required=False, default='')
    user_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=99, allow_empty=False)


class ManageRoomSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['rename', 'add', 'remove', 'leave', 'transfer', 'close'])
    name = serializers.CharField(max_length=100, required=False)
    user_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        if attrs['action'] == 'rename' and not attrs.get('name'):
            raise serializers.ValidationError('请填写群名称。')
        if attrs['action'] in {'add', 'remove', 'transfer'} and not attrs.get('user_id'):
            raise serializers.ValidationError('请选择成员。')
        return attrs


class ReadSerializer(serializers.Serializer):
    message_id = serializers.IntegerField(min_value=0)


class PageSerializer(serializers.Serializer):
    before = serializers.IntegerField(min_value=1, required=False)
    after_revision = serializers.IntegerField(min_value=0, required=False)

from rest_framework import serializers
from . import models as m


class PrivateSerializer(serializers.ModelSerializer):
    revision = serializers.IntegerField(required=False, min_value=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        scope = self.context.get('scope')
        if scope:
            for field in self.fields.values():
                relation = field.child_relation if isinstance(field, serializers.ManyRelatedField) else field
                if not isinstance(relation, serializers.PrimaryKeyRelatedField) or relation.queryset is None:
                    continue
                model = relation.queryset.model
                if model is m.Work:
                    relation.queryset = relation.queryset.filter(**{f'account__{k}': v for k, v in scope.items()})
                elif model is m.ScriptVersion:
                    relation.queryset = relation.queryset.filter(**{f'task__{k}': v for k, v in scope.items()})
                else:
                    relation.queryset = relation.queryset.filter(**scope)

    def validate(self, attrs):
        for key, value in attrs.items():
            if isinstance(value, str) and len(value) > 20000:
                raise serializers.ValidationError({key: '内容不能超过20000字。'})
        tags = attrs.get('tags', [])
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in tags):
            raise serializers.ValidationError({'tags': '最多20个标签，每个1–40字。'})
        return attrs


BASE = ['id', 'revision', 'created_at', 'updated_at']
READ = ['id', 'created_at', 'updated_at']


class ProfileSerializer(PrivateSerializer):
    active_version_number = serializers.IntegerField(source='active_version.number', read_only=True, allow_null=True)

    class Meta:
        model = m.CreatorProfile
        fields = BASE + ['name', 'positioning', 'audience', 'experiences', 'products', 'voice', 'conditions', 'is_default',
                         'account', 'content_pillars', 'content_boundaries', 'shared_inspiration_ids', 'active_version', 'active_version_number']
        read_only_fields = READ + ['active_version']
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        account = attrs.get('account', getattr(self.instance, 'account', None))
        if account and not account.is_owned:
            raise serializers.ValidationError('请先将账号标记为我的账号。')
        if self.instance and 'account' in attrs and self.instance.account_id and getattr(account, 'pk', None) != self.instance.account_id:
            raise serializers.ValidationError('已有账号档案不能更换账号。')
        if self.instance and 'account' in attrs and not self.instance.account_id and self.instance.voice_versions.exists():
            raise serializers.ValidationError('有历史文风版本的档案不能绑定其他账号，请新建独立档案。')
        if 'shared_inspiration_ids' in attrs:
            from .owned import shared_materials
            attrs['shared_inspiration_ids'] = [r['id'] for r in shared_materials(self.context['scope'], attrs['shared_inspiration_ids'])]
        return attrs


class InspirationSerializer(PrivateSerializer):
    kind = serializers.ChoiceField(choices=['work', 'segment', 'hook', 'frame', 'text'], default='work')
    source_time = serializers.FloatField(required=False, allow_null=True, min_value=0, max_value=36000)

    class Meta:
        model = m.Inspiration
        fields = BASE + ['title', 'kind', 'text', 'notes', 'tags', 'work', 'source_task', 'source_ref', 'source_time']
        read_only_fields = READ

    def validate(self, attrs):
        attrs = super().validate(attrs)
        source = attrs.get('source_task', getattr(self.instance, 'source_task', None))
        work = attrs.get('work', getattr(self.instance, 'work', None))
        ref = attrs.get('source_ref', getattr(self.instance, 'source_ref', ''))
        if source and work and source.work_id and source.work_id != work.pk:
            raise serializers.ValidationError('作品与来源任务不匹配。')
        if ref:
            allowed = {str(i['id']) for k in ['segments', 'frames'] for i in (source.output.get(k, []) if source else [])}
            if ref not in allowed:
                raise serializers.ValidationError('来源片段不存在。')
        return attrs


class IdeaSerializer(PrivateSerializer):
    status = serializers.ChoiceField(choices=['research', 'create', 'shoot', 'published'], default='research')
    class Meta:
        model = m.Idea
        fields = BASE + ['title', 'notes', 'tags', 'status', 'position', 'inspiration', 'source_task']
        read_only_fields = READ


class PublicationSerializer(PrivateSerializer):
    work_detail = serializers.SerializerMethodField()
    class Meta:
        model = m.Publication
        fields = BASE + ['work', 'idea', 'script_version', 'theme', 'title', 'hook', 'notes', 'work_detail']
        read_only_fields = READ
        validators = []

    def get_work_detail(self, obj):
        from .research import work_data
        return work_data(obj.work)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        work = attrs.get('work', getattr(self.instance, 'work', None))
        if work and not work.account.is_owned:
            raise serializers.ValidationError('请先将该账号标记为我的账号。')
        version = attrs.get('script_version', getattr(self.instance, 'script_version', None))
        if version and version.task.kind not in ['script', 'rewrite', 'article']:
            raise serializers.ValidationError('请选择文章、脚本或改写文案的保存版本。')
        target = version.task.input.get('brief', {}).get('target_account_id') if version else None
        if target and work and str(work.account_id) != target:
            raise serializers.ValidationError('文案与发布作品不属于同一个创作账号。')
        return attrs


class SubscriptionSerializer(PrivateSerializer):
    interval_hours = serializers.ChoiceField(choices=[6, 12, 24], default=24)
    count = serializers.ChoiceField(choices=[20, 50, 100], default=50)
    class Meta:
        model = m.Subscription
        fields = BASE + ['account', 'enabled', 'interval_hours', 'count', 'tracked_works', 'rules', 'next_run_at', 'blocked_reason']
        read_only_fields = READ + ['next_run_at', 'blocked_reason']
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        account = attrs.get('account', getattr(self.instance, 'account', None))
        if self.instance and account.pk != self.instance.account_id:
            raise serializers.ValidationError('订阅不能更换账号。')
        works = attrs.get('tracked_works', [])
        if len(works) > 20 or any(w.account_id != account.pk for w in works):
            raise serializers.ValidationError('最多追踪该账号的20条作品。')
        rules = attrs.get('rules', {})
        if not isinstance(rules, dict) or set(rules) - {'percent', 'likes', 'comments', 'collects'}:
            raise serializers.ValidationError('增长规则字段无效。')
        for key, value in rules.items():
            if type(value) not in (int, float) or not 0 <= value <= 100000000 or value != value:
                raise serializers.ValidationError('增长阈值必须为有效的非负数字。')
        return attrs


class NotificationSerializer(PrivateSerializer):
    class Meta:
        model = m.Notification
        fields = BASE + ['kind', 'title', 'body', 'account', 'work', 'read']
        read_only_fields = READ + ['kind', 'title', 'body', 'account', 'work']


class DigestSerializer(PrivateSerializer):
    class Meta:
        model = m.Digest
        fields = BASE + ['day', 'body']
        read_only_fields = BASE + ['day', 'body']


class ResearchInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['radar', 'radar_hotlist', 'radar_search', 'radar_topics', 'joint', 'compare', 'comments', 'needs', 'variants', 'review', 'refresh', 'topics', 'script', 'voice_analysis', 'article', 'knowledge_extract'])
    keyword = serializers.CharField(max_length=100, required=False)
    source_ids = serializers.ListField(child=serializers.CharField(max_length=400), min_length=1, max_length=20, required=False)
    knowledge_cards = serializers.ListField(child=serializers.DictField(), max_length=10, required=False)
    target_account_id = serializers.UUIDField(required=False)
    analysis_mode = serializers.ChoiceField(choices=['style', 'positioning'], default='style')
    account_ids = serializers.ListField(child=serializers.UUIDField(), max_length=50, default=list)
    work_ids = serializers.ListField(child=serializers.UUIDField(), max_length=20, default=list)
    days = serializers.ChoiceField(choices=[7, 30, 90], default=30)
    group = serializers.CharField(max_length=100, allow_blank=True, default='')
    count = serializers.ChoiceField(choices=[50, 100, 200], default=100)
    include_replies = serializers.BooleanField(default=False)
    source_task_id = serializers.UUIDField(required=False)
    source_version_id = serializers.UUIDField(required=False)
    profile_id = serializers.UUIDField(required=False, allow_null=True)
    idea_id = serializers.UUIDField(required=False)
    topic_index = serializers.IntegerField(min_value=0, max_value=2, default=0)
    positioning = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    audience = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    theme = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    writing_requirements = serializers.CharField(max_length=3000, allow_blank=True, required=False)
    factual_material = serializers.CharField(max_length=10000, allow_blank=True, required=False)
    conditions = serializers.CharField(max_length=3000, allow_blank=True, required=False)
    duration = serializers.IntegerField(min_value=15, max_value=600, default=60)
    production_format = serializers.ChoiceField(choices=['talking_head', 'screencast', 'animation', 'live_action', 'mixed'], default='talking_head')
    brand_profile_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs['account_ids'] = list(dict.fromkeys(attrs['account_ids']))
        attrs['work_ids'] = list(dict.fromkeys(attrs['work_ids']))
        kind = attrs['kind']
        if kind == 'radar_search' and not attrs.get('keyword'):
            raise serializers.ValidationError('请输入要搜索的关键词。')
        if kind == 'radar_topics':
            if not attrs.get('source_task_id') or not attrs.get('source_ids'):
                raise serializers.ValidationError('请选择一次已完成采集中的1–20条来源。')
            attrs['source_ids'] = list(dict.fromkeys(attrs['source_ids']))
        if kind == 'voice_analysis' and not attrs.get('target_account_id'):
            raise serializers.ValidationError('请选择自己的账号。')
        if kind == 'joint' and not 2 <= len(attrs['work_ids']) <= 5:
            raise serializers.ValidationError('联合拆解请选择2–5条视频。')
        if kind == 'compare' and not 2 <= len(attrs['account_ids']) <= 5:
            raise serializers.ValidationError('账号对比请选择2–5个账号。')
        if kind == 'comments' and len(attrs['work_ids']) != 1:
            raise serializers.ValidationError('请选择一条作品采集评论。')
        if kind == 'refresh' and not attrs['work_ids']:
            raise serializers.ValidationError('请选择需要刷新的作品。')
        if kind in ['needs', 'knowledge_extract'] and not attrs.get('source_task_id'):
            raise serializers.ValidationError('请选择来源任务。')
        if kind in ['script', 'article']:
            if not attrs.get('source_task_id') and not attrs.get('idea_id') and not attrs.get('theme'):
                raise serializers.ValidationError('请输入这次想写的主题，或选择已有选题。')
            if attrs.get('source_task_id') and attrs.get('idea_id'):
                raise serializers.ValidationError('请选择一种选题来源。')
        if attrs.get('writing_requirements') or attrs.get('factual_material'):
            if kind not in ['article', 'script'] or attrs.get('source_task_id'):
                raise serializers.ValidationError('新增写作要求或真实素材时，请使用直接输入或选题库写作；历史选题沿用原有资料。')
        if 'knowledge_cards' in attrs:
            from .knowledge import CardSelection
            if kind != 'topics' and not (kind in ['article', 'script'] and not attrs.get('source_task_id')):
                raise serializers.ValidationError('请在生成选题时选择知识。')
            fields = CardSelection(data=attrs['knowledge_cards'], many=True)
            fields.is_valid(raise_exception=True)
            attrs['knowledge_cards'] = fields.validated_data
        if kind == 'variants' and not attrs.get('source_version_id'):
            raise serializers.ValidationError('请选择已保存的文案版本。')
        if attrs['production_format'] == 'animation' and attrs['duration'] > 120:
            raise serializers.ValidationError('动画演示最长120秒。')
        return attrs

"""Typed business payloads. JSON storage never bypasses field/reference validation."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from rest_framework import serializers as s

PLATFORMS = ['xiaohongshu', 'douyin', 'channels', 'moments']
TYPES = ['property', 'comparison', 'guide', 'qa']
STAGES = ['new', 'qualified', 'recommended', 'scheduled', 'viewed', 'won', 'paused', 'lost']
STATUSES = {'properties': ['available', 'rented', 'paused'], 'personas': ['active'], 'leads': STAGES,
            'followups': ['pending', 'done', 'cancelled'], 'viewings': ['scheduled', 'done', 'cancelled', 'no_show'],
            'contents': ['draft'], 'publications': ['draft', 'planned', 'published', 'cancelled']}


def text(limit=3000):
    return s.CharField(required=False, default='', allow_blank=True, max_length=limit)


def ids():
    return s.ListField(child=s.UUIDField(), required=False, default=list, max_length=50)


def money():
    return s.FloatField(required=False, default=None, allow_null=True, min_value=0, max_value=10000000)


class StrictSerializer(s.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            extra = set(data) - set(self.fields)
            if extra:
                raise s.ValidationError({key: '不支持的字段。' for key in sorted(extra)})
        return super().to_internal_value(data)


class Photo(StrictSerializer):
    label = s.CharField(max_length=100)
    note = text(500)


class Requirements(StrictSerializer):
    budget_min = money()
    budget_max = money()
    city = text(100)
    districts = s.ListField(child=s.CharField(max_length=100), required=False, default=list, max_length=30)
    rental_type = s.ChoiceField(choices=['', 'whole', 'shared'], required=False, default='')
    layout = text(100)
    move_in = s.DateField(required=False, allow_null=True, default=None)
    # Exact user-defined conditions; unknown is not equivalent to false.
    must_have = s.ListField(child=s.CharField(max_length=100), required=False, default=list, max_length=30)
    needs = text()
    concerns = text()

    def validate(self, data):
        if data.get('budget_min') is not None and data.get('budget_max') is not None and data['budget_min'] > data['budget_max']:
            raise s.ValidationError('最低预算不能大于最高预算。')
        return data


class PropertyData(StrictSerializer):
    city = text(100)
    district = text(100)
    location = text(300)
    rent = money()
    rental_type = s.ChoiceField(choices=['', 'whole', 'shared'], default='', required=False)
    layout = text(100)
    area = s.FloatField(min_value=0, max_value=100000, allow_null=True, default=None, required=False)
    floor = text(100)
    elevator = s.ChoiceField(choices=['unknown', 'yes', 'no'], default='unknown', required=False)
    transport = text()
    amenities = text()
    fees = text()
    available_from = s.DateField(required=False, allow_null=True, default=None)
    pets = s.ChoiceField(choices=['unknown', 'yes', 'no'], default='unknown', required=False)
    strengths = text()
    drawbacks = text()
    conditions = s.DictField(child=s.ChoiceField(choices=['yes', 'no', 'unknown']), required=False, default=dict)
    photos = Photo(many=True, required=False, default=list)

    def validate_photos(self, value):
        if len(value) > 30:
            raise s.ValidationError('最多记录 30 张照片。')
        return value


class LeadData(Requirements):
    contact = text(200)
    platform = s.ChoiceField(choices=['unknown'] + PLATFORMS, default='unknown', required=False)
    source_id = s.UUIDField(required=False, allow_null=True, default=None)
    property_ids = ids()
    notes = text(10000)
    consulted_on = s.DateField()
    deal_date = s.DateField(required=False, allow_null=True, default=None)
    deal_property_id = s.UUIDField(required=False, allow_null=True, default=None)


class FollowUpData(StrictSerializer):
    next_due_date = s.DateField(required=False, allow_null=True, default=None)
    due_date = s.DateField()
    summary = text(10000)
    outcome = text()
    next_step = text()


class ViewingData(StrictSerializer):
    scheduled_at = s.DateTimeField()
    property_ids = ids()
    meeting_place = text(500)
    notes = text()
    feedback = text()
    next_step = text()

    def validate_property_ids(self, value):
        if not value:
            raise s.ValidationError('请选择至少一套房源。')
        return value


class ContentData(StrictSerializer):
    planned_date = s.DateField(required=False, allow_null=True, default=None)
    platform = s.ChoiceField(choices=PLATFORMS, default='xiaohongshu', required=False)
    content_type = s.ChoiceField(choices=TYPES, default='property', required=False)
    property_ids = ids()
    persona_id = s.UUIDField(required=False, allow_null=True, default=None)
    angle = text()


class PublicationData(StrictSerializer):
    scheduled_date = s.DateField(required=False, allow_null=True, default=None)
    published_at = s.DateTimeField(required=False, allow_null=True, default=None)
    url = s.URLField(required=False, allow_blank=True, default='', max_length=2000)
    notes = text()


class Page(StrictSerializer):
    photo_ref = text(100)
    caption = text(2000)
    layout = text(2000)


class CopyBody(StrictSerializer):
    titles = s.ListField(child=s.CharField(max_length=200), min_length=1, max_length=3)
    cover = text(1000)
    body = s.CharField(max_length=20000)
    tags = s.ListField(child=s.CharField(max_length=100), max_length=15, required=False, default=list)
    pages = Page(many=True, required=False, default=list)
    script = text(10000)
    shots = s.ListField(child=s.CharField(max_length=2000), max_length=30, required=False, default=list)
    checks = s.ListField(child=s.CharField(max_length=1000), max_length=30, required=False, default=list)


class MetricData(StrictSerializer):
    views = s.IntegerField(min_value=0, allow_null=True, default=None, required=False)
    likes = s.IntegerField(min_value=0, allow_null=True, default=None, required=False)
    saves = s.IntegerField(min_value=0, allow_null=True, default=None, required=False)
    comments = s.IntegerField(min_value=0, allow_null=True, default=None, required=False)


class SettingsData(StrictSerializer):
    timezone = s.CharField(default='Asia/Shanghai', required=False)
    voice = s.CharField(max_length=3000, default='自然、具体的中介介绍，不夸张承诺。', required=False)
    platform = s.ChoiceField(choices=PLATFORMS, default='xiaohongshu', required=False)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise s.ValidationError('请输入有效时区，例如 Asia/Shanghai。')
        return value


SCHEMAS = {'properties': PropertyData, 'personas': Requirements, 'leads': LeadData,
           'followups': FollowUpData, 'viewings': ViewingData, 'contents': ContentData, 'publications': PublicationData}


def validated(cls, value):
    serializer = cls(data=value)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.data)

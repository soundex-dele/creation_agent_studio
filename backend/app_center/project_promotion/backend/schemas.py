from rest_framework import serializers as s
from django.core.validators import URLValidator
from .catalog import MATERIAL_TYPES

PLATFORMS = ['wechat', 'xiaohongshu', 'douyin', 'moments']
DIRECTIONS = ['overview', 'application_overview', 'audience', 'demo', 'solution', 'workflow', 'showcase', 'comparison',
              'tutorial', 'architecture', 'boundaries', 'development', 'experience']


class Strict(s.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise s.ValidationError('包含不支持的字段。')
        return super().to_internal_value(data)


def text(size=10000):
    return s.CharField(max_length=size, allow_blank=True, required=False, default='')


class HttpURL(s.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validators.append(URLValidator(schemes=['http', 'https']))


class Asset(Strict):
    label = s.CharField(max_length=200)
    kind = s.ChoiceField(choices=['image', 'video', 'document', 'link'], default='link')
    url = HttpURL(max_length=2000)
    note = text(2000)


class CaseData(Strict):
    material_type = s.ChoiceField(choices=MATERIAL_TYPES, default='case')
    summary = text(2000)
    facts = text()
    case_type = s.ChoiceField(choices=['demo', 'customer'], default='demo')
    category = s.ChoiceField(choices=['general', 'wechat', 'multichannel', 'automation'], default='general')
    audience = text(2000)
    problem = text()
    solution = text()
    steps = text()
    evidence = text()
    implemented = text()
    conditions = text()
    extensions = text()
    development_notes = text(30000)
    assets = Asset(many=True, required=False, default=list, max_length=40)


class TopicData(Strict):
    direction = s.ChoiceField(choices=DIRECTIONS, default='demo')
    audience = text(2000)
    angle = text(5000)
    thesis = text(5000)
    outline = text()
    source_feedback_id = s.UUIDField(required=False, allow_null=True, default=None)


class ChannelData(Strict):
    planned_date = s.DateField(required=False, allow_null=True, default=None)
    published_at = s.DateTimeField(required=False, allow_null=True, default=None)
    publication_url = HttpURL(max_length=2000, allow_blank=True, default='')


class FeedbackData(Strict):
    observed_on = s.DateField()
    views = s.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    interactions = s.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    inquiries = s.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    questions = text()
    notes = text()


class CopyBody(Strict):
    title = s.CharField(max_length=200)
    body = s.CharField(max_length=50000)
    cover = text(1000)
    pages = text(20000)
    script = text(20000)
    materials = text()
    shots = text()
    checks = text()
    formatted_html = text(100000)


SCHEMAS = {'cases': CaseData, 'topics': TopicData, 'channels': ChannelData, 'feedback': FeedbackData}
STATUSES = {'cases': ['draft', 'confirmed'], 'topics': ['draft', 'confirmed'],
            'channels': ['draft', 'ready', 'published', 'paused'], 'feedback': ['recorded']}


def validated(cls, data):
    serializer = cls(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.data)

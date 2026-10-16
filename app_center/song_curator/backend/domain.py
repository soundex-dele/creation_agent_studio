import hashlib
import json
import re
import unicodedata
from uuid import uuid4
from rest_framework import serializers as s

ACTIVE = {'queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'}
DEFAULTS = {'language': 'follow', 'exploration': 'balanced', 'excludeHeard': True}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value).strip()).casefold()


def title_version(title, version=''):
    title = normalized(title)
    version = normalized(version)
    match = re.search(r'\s*[（(\[]([^()（）\[\]]+)[）)\]]\s*$', title)
    if match and any(marker in match.group(1) for marker in ('live', '现场', '現場', 'remix', 'acoustic', 'instrumental', '伴奏', 'remaster')):
        version = version or match.group(1)
        title = title[:match.start()].strip()
    return title, version


def identity(track):
    title, version = title_version(track.get('title', ''), track.get('version', ''))
    return '|'.join((title, normalized(track.get('artist', '')), version))


class TrackInput(s.Serializer):
    title = s.CharField(max_length=300)
    artist = s.CharField(max_length=300, allow_blank=True, default='')
    album = s.CharField(max_length=300, allow_blank=True, default='')
    version = s.CharField(max_length=120, allow_blank=True, default='')


def tracks_validated(rows, *, draft=False):
    if not isinstance(rows, list) or len(rows) > 500:
        raise s.ValidationError('每批最多 500 首歌曲。')
    output, seen = [], set()
    for row in rows:
        validator = TrackInput(data=row)
        validator.is_valid(raise_exception=True)
        track = dict(validator.validated_data)
        if identity(track) in seen:
            continue
        seen.add(identity(track))
        track['id'] = str(uuid4())
        if draft:
            track['sourceImageId'] = str(row.get('sourceImageId') or '')
            track['note'] = str(row.get('note') or '')[:500]
        output.append(track)
    return output


class Preferences(s.Serializer):
    language = s.ChoiceField(choices=['follow', 'any', 'zh', 'en', 'ja-ko'], default='follow')
    exploration = s.ChoiceField(choices=['close', 'balanced', 'explore'], default='balanced')
    excludeHeard = s.BooleanField(default=True)


class Filters(s.Serializer):
    genre = s.CharField(max_length=120, allow_blank=True, default='')
    mood = s.CharField(max_length=120, allow_blank=True, default='')
    scene = s.CharField(max_length=120, allow_blank=True, default='')
    decade = s.CharField(max_length=50, allow_blank=True, default='')
    language = s.ChoiceField(choices=['follow', 'any', 'zh', 'en', 'ja-ko'], required=False)
    exploration = s.ChoiceField(choices=['close', 'balanced', 'explore'], required=False)


class TaskInput(s.Serializer):
    requestKey = s.CharField(max_length=160)
    revision = s.IntegerField(min_value=0)
    kind = s.ChoiceField(choices=['import', 'similar', 'conditions'])
    imageIds = s.ListField(child=s.UUIDField(), max_length=5, default=list)
    playlistId = s.UUIDField(required=False)
    trackIds = s.ListField(child=s.UUIDField(), max_length=500, default=list)
    filters = Filters(default=dict)

    def validate(self, value):
        if value['kind'] == 'import' and not value['imageIds']:
            raise s.ValidationError('请上传 1 至 5 张图片，或使用手动录入。')
        if len(set(value['imageIds'])) != len(value['imageIds']):
            raise s.ValidationError('图片不能重复。')
        if value['kind'] == 'similar' and not value.get('playlistId'):
            raise s.ValidationError('请选择种子歌单。')
        if value['kind'] != 'import' and value['imageIds']:
            raise s.ValidationError('图片仅用于识别任务。')
        return value


class Mutation(s.Serializer):
    requestKey = s.CharField(max_length=160)
    revision = s.IntegerField(min_value=0)
    action = s.ChoiceField(choices=['create', 'rename', 'delete', 'add', 'remove', 'confirm', 'feedback', 'preferences'])
    playlistId = s.UUIDField(required=False)
    taskId = s.UUIDField(required=False)
    name = s.CharField(max_length=120, required=False)
    tracks = TrackInput(many=True, required=False, max_length=500)
    trackIds = s.ListField(child=s.UUIDField(), max_length=500, required=False)
    feedback = s.ChoiceField(choices=['like', 'dislike', 'heard', 'none'], required=False)
    preferences = Preferences(required=False)

    def validate(self, value):
        required = {'create': ['name'], 'rename': ['playlistId', 'name'], 'delete': ['playlistId'],
                    'add': ['playlistId', 'tracks'], 'remove': ['playlistId', 'trackIds'],
                    'confirm': ['taskId', 'tracks'], 'feedback': ['tracks', 'feedback'], 'preferences': ['preferences']}
        if any(key not in value for key in required[value['action']]):
            raise s.ValidationError('缺少本次操作所需的字段。')
        if value['action'] == 'confirm' and not (value.get('playlistId') or value.get('name')):
            raise s.ValidationError('请选择目标歌单或填写新歌单名称。')
        if value['action'] == 'feedback' and len(value['tracks']) != 1:
            raise s.ValidationError('请选择一首歌曲进行反馈。')
        if value['action'] in ('add', 'confirm') and not value['tracks']:
            raise s.ValidationError('请至少保留一首歌曲。')
        return value

import hashlib
import json
import logging
import time
import uuid
from functools import wraps

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import OperationalError, connection, transaction
from django.db.models import BigIntegerField, Count, F, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .models import Attachment, Membership, Message, Room

logger = logging.getLogger(__name__)
MAX_BYTES = 100 * 1024 * 1024


def retry_db_busy(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        for attempt in range(5):
            try:
                return func(*args, **kwargs)
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower() or attempt == 4 or connection.in_atomic_block:
                    raise
                time.sleep(0.025 * 2 ** attempt)
    return wrapped


class Conflict(APIException):
    status_code = 409
    default_detail = '请求内容发生变化，请重新提交。'


def visible_rooms(user):
    return Room.objects.filter(closed=False).filter(Q(kind='lobby') | Q(memberships__user=user)).distinct()


def room_for(user, room_id, *, lock=False):
    # Lock before inspecting membership: removal and writes serialize on the room.
    if lock:
        # Acquire a write reservation on SQLite too, before any transactional read.
        Room.objects.filter(pk=room_id).update(version=F('version'))
    qs = Room.objects.select_for_update() if lock else Room.objects
    room = get_object_or_404(qs, pk=room_id, closed=False)
    if room.kind != 'lobby' and not Membership.objects.filter(room=room, user=user).exists():
        raise PermissionDenied('你已不在此会话中。')
    return room


def bump(room):
    room.version += 1
    room.save(update_fields=['version', 'updated_at', 'name', 'owner', 'closed'])


def notify(room, extra_users=()):
    targets = ['community.lobby'] if room.kind == 'lobby' else [
        f'community.user.{uid}' for uid in set(room.memberships.values_list('user_id', flat=True)) | set(extra_users)]
    event = {'type': 'chat.changed', 'room': str(room.pk), 'version': room.version, 'event_id': uuid.uuid4().hex}

    def publish():
        try:
            layer = get_channel_layer()
            for target in targets:
                async_to_sync(layer.group_send)(target, event)
        except Exception:
            # Durable data remains available via HTTP reconciliation.
            logger.warning('Community delivery failed room=%s', room.pk)
    transaction.on_commit(publish)


def user_data(user):
    return {'id': user.pk, 'username': user.username, 'nickname': user.get_full_name() or user.username, 'avatar': user.avatar}


def attachment_data(item):
    return {'id': str(item.pk), 'name': item.name, 'size': item.size, 'image': item.image, 'content_type': item.content_type}


def message_data(item):
    return {'id': item.pk, 'room_id': str(item.room_id), 'author': user_data(item.author),
            'text': '' if item.withdrawn else item.text, 'withdrawn': item.withdrawn,
            'request_key': item.request_key, 'revision': item.revision, 'created_at': item.created_at.isoformat(),
            'attachments': [] if item.withdrawn else [attachment_data(a) for a in item.attachments.all()]}


def room_data(room, user):
    members = getattr(room, 'loaded_members', None)
    if members is None:
        members = list(room.memberships.select_related('user'))
    membership = next((m for m in members if m.user_id == user.pk), None)
    last_read = membership.last_read_id if membership else 0
    peer = next((m for m in members if m.user_id != user.pk), None) if room.kind == 'direct' else None
    if hasattr(room, 'latest_text'):
        preview = '开始交流吧'
        if room.latest_text is not None:
            preview = '消息已撤回' if room.latest_withdrawn else room.latest_text[:80] or '[图片 / 文件]'
        unread = room.unread_total
    else:
        latest = room.messages.order_by('-id').first()
        preview = ('消息已撤回' if latest.withdrawn else latest.text[:80] or '[图片 / 文件]') if latest else '开始交流吧'
        unread = room.messages.filter(id__gt=last_read, withdrawn=False).exclude(author=user).count()
    return {'id': str(room.pk), 'kind': room.kind, 'name': user_data(peer.user)['nickname'] if peer else room.name,
            'owner_id': room.owner_id, 'version': room.version, 'last_read_id': last_read,
            'unread': unread, 'member_count': len(members), 'preview': preview,
            'updated_at': room.updated_at.isoformat()}


def room_list(user):
    read = Membership.objects.filter(room_id=OuterRef('pk'), user=user).values('last_read_id')[:1]
    latest = Message.objects.filter(room_id=OuterRef('pk')).order_by('-id')
    unread = Message.objects.filter(room_id=OuterRef('pk'), id__gt=OuterRef('read_marker'), withdrawn=False).exclude(author=user).values('room_id').annotate(total=Count('pk')).values('total')
    rooms = visible_rooms(user).annotate(
        read_marker=Coalesce(Subquery(read), Value(0), output_field=BigIntegerField()),
        latest_text=Subquery(latest.values('text')[:1]),
        latest_withdrawn=Subquery(latest.values('withdrawn')[:1]),
        unread_total=Coalesce(Subquery(unread), Value(0)),
    ).prefetch_related(Prefetch('memberships', queryset=Membership.objects.select_related('user'), to_attr='loaded_members')).order_by('-updated_at')
    return [room_data(room, user) for room in rooms]


@retry_db_busy
def send_message(user, room_id, data):
    started = time.monotonic()
    payload = {'text': data['text'], 'attachments': sorted(str(a) for a in data['attachments'])}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with transaction.atomic():
        room = room_for(user, room_id, lock=True)
        existing = room.messages.filter(author=user, request_key=data['request_key']).first()
        if existing:
            if existing.payload_hash != digest:
                raise Conflict()
            return existing
        attachments = list(Attachment.objects.select_for_update().filter(pk__in=data['attachments'], owner=user, room=room, message=None))
        if len(attachments) != len(data['attachments']):
            raise ValidationError('附件无效、已发送或不属于此会话。')
        if sum(a.size for a in attachments) > MAX_BYTES:
            raise ValidationError('每条消息的附件总大小不能超过 100MB。')
        bump(room)
        item = Message.objects.create(room=room, author=user, text=data['text'], request_key=data['request_key'], payload_hash=digest, revision=room.version)
        Attachment.objects.filter(pk__in=[a.pk for a in attachments]).update(message=item)
        notify(room)
    logger.info('Community send room=%s duration_ms=%d', room_id, (time.monotonic() - started) * 1000)
    return item


def withdraw(user, room_id, message_id):
    with transaction.atomic():
        room = room_for(user, room_id, lock=True)
        item = get_object_or_404(Message, room=room, pk=message_id, author=user)
        if item.withdrawn:
            return item
        if (timezone.now() - item.created_at).total_seconds() > 120:
            raise ValidationError('只能撤回两分钟内发送的消息。')
        bump(room)
        item.withdrawn, item.text, item.revision = True, '', room.version
        item.save(update_fields=['withdrawn', 'text', 'revision'])
        notify(room)
        return item

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import Membership, Message, Room, SocketTicket
from .serializers import CreateRoomSerializer, ManageRoomSerializer, PageSerializer, ReadSerializer, SendSerializer
from .services import bump, message_data, notify, retry_db_busy, room_data, room_for, room_list, send_message, user_data, withdraw


class ChatWriteThrottle(UserRateThrottle):
    scope = 'community-write'
    rate = '120/min'


class AuthView(APIView):
    permission_classes = [IsAuthenticated]


def validated(cls, data):
    serializer = cls(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class UsersView(AuthView):
    def get(self, request):
        query = request.query_params.get('q', '')[:100].strip()
        users = get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk)
        if query:
            users = users.filter(Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
        return Response({'me': user_data(request.user), 'users': [user_data(u) for u in users.order_by('username')[:50]]})


class RoomsView(AuthView):
    def get(self, request):
        Room.objects.get_or_create(unique_key='lobby', defaults={'kind': 'lobby', 'name': '公共大厅'})
        return Response(room_list(request.user))

    @retry_db_busy
    def post(self, request):
        data = validated(CreateRoomSerializer, request.data)
        ids = set(data['user_ids']) - {request.user.pk}
        if not ids or get_user_model().objects.filter(pk__in=ids, is_active=True).count() != len(ids):
            raise ValidationError('请选择有效用户。')
        if data['kind'] == 'direct' and len(ids) != 1:
            raise ValidationError('私聊只能选择一位用户。')
        if data['kind'] == 'group' and not data['name'].strip():
            raise ValidationError('请填写群名称。')
        with transaction.atomic():
            if data['kind'] == 'direct':
                key = 'direct:' + ':'.join(str(i) for i in sorted(ids | {request.user.pk}))
                room, _ = Room.objects.get_or_create(unique_key=key, defaults={'kind': 'direct'})
            else:
                room = Room.objects.create(kind='group', name=data['name'], owner=request.user)
            for uid in ids | {request.user.pk}:
                Membership.objects.get_or_create(room=room, user_id=uid)
            notify(room)
            return Response(room_data(room, request.user), status=201)


class RoomView(AuthView):
    def get(self, request, room_id):
        room = room_for(request.user, room_id)
        return Response({**room_data(room, request.user), 'members': [user_data(m.user) for m in room.memberships.select_related('user')]})

    def patch(self, request, room_id):
        data = validated(ManageRoomSerializer, request.data)
        with transaction.atomic():
            room = room_for(request.user, room_id, lock=True)
            if room.kind != 'group':
                raise ValidationError('只有群聊可以管理成员。')
            action, uid = data['action'], data.get('user_id')
            if action != 'leave' and room.owner_id != request.user.pk:
                raise PermissionDenied('只有群主可以执行此操作。')
            previous = list(room.memberships.values_list('user_id', flat=True))
            if action == 'rename':
                room.name = data['name']
            elif action == 'add':
                user = get_object_or_404(get_user_model(), pk=uid, is_active=True)
                if room.memberships.count() >= 100:
                    raise ValidationError('群成员最多 100 人。')
                Membership.objects.get_or_create(room=room, user=user)
            elif action == 'remove':
                if uid == room.owner_id:
                    raise ValidationError('请先转让群主。')
                room.memberships.filter(user_id=uid).delete()
            elif action == 'leave':
                if room.owner_id == request.user.pk:
                    raise ValidationError('请先转让群主，或解散群聊。')
                room.memberships.filter(user=request.user).delete()
            elif action == 'transfer':
                member = get_object_or_404(Membership, room=room, user_id=uid, user__is_active=True)
                room.owner = member.user
            elif action == 'close':
                room.closed = True
            bump(room)
            notify(room, previous)
        return Response({'ok': True})


class MessagesView(AuthView):
    def get(self, request, room_id):
        params = validated(PageSerializer, request.query_params)
        # Version and rows must belong to the same snapshot; room mutations lock it.
        with transaction.atomic():
            room = room_for(request.user, room_id, lock=True)
            qs = room.messages.select_related('author').prefetch_related('attachments')
            if 'after_revision' in params:
                items = list(qs.filter(revision__gt=params['after_revision']).order_by('revision', 'id')[:201])
                more = len(items) > 200
                items = items[:200]
                revision = items[-1].revision if more else room.version
            else:
                if params.get('before'):
                    qs = qs.filter(id__lt=params['before'])
                items = list(qs.order_by('-id')[:51])
                more = len(items) > 50
                items = list(reversed(items[:50]))
                revision = room.version
            return Response({'messages': [message_data(m) for m in items], 'revision': revision, 'has_more': more})

    def post(self, request, room_id):
        throttle = ChatWriteThrottle()
        if not throttle.allow_request(request, self):
            self.throttled(request, throttle.wait())
        item = send_message(request.user, room_id, validated(SendSerializer, request.data))
        return Response(message_data(item), status=201)


class WithdrawView(AuthView):
    def post(self, request, room_id, message_id):
        return Response(message_data(withdraw(request.user, room_id, message_id)))


class ReadView(AuthView):
    def post(self, request, room_id):
        data = validated(ReadSerializer, request.data)
        with transaction.atomic():
            room = room_for(request.user, room_id, lock=True)
            if data['message_id']:
                get_object_or_404(Message, room=room, pk=data['message_id'])
            member, _ = Membership.objects.get_or_create(room=room, user=request.user)
            member.last_read_id = max(member.last_read_id, data['message_id'])
            member.save(update_fields=['last_read_id'])
            # Read changes only invalidate this user's sessions, not every member.
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            def publish():
                try:
                    async_to_sync(get_channel_layer().group_send)(f'community.user.{request.user.pk}',
                        {'type': 'chat.changed', 'room': str(room.pk), 'version': room.version, 'event_id': uuid.uuid4().hex})
                except Exception:
                    pass
            transaction.on_commit(publish)
        return Response({'last_read_id': member.last_read_id})


class TicketView(AuthView):
    throttle_classes = [ChatWriteThrottle]

    def post(self, request):
        raw = secrets.token_urlsafe(32)
        SocketTicket.objects.create(digest=hashlib.sha256(raw.encode()).hexdigest(), user=request.user,
                                    expires_at=timezone.now() + timedelta(seconds=30))
        return Response({'ticket': raw, 'expires_in': 30})

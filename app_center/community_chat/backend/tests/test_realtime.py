import asyncio
import hashlib
import secrets
import statistics
import time
from datetime import timedelta

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.utils import timezone

from ..consumer import socket_application
from ..models import Room, SocketTicket
from ..services import send_message


@database_sync_to_async
def provision(count):
    user = get_user_model().objects.create_user(username='socket-user')
    other = get_user_model().objects.create_user(username='socket-peer')
    room = Room.objects.create(kind='lobby', unique_key='lobby', name='大厅')
    keys = [secrets.token_urlsafe(32) for _ in range(count)]
    SocketTicket.objects.bulk_create([SocketTicket(digest=hashlib.sha256(key.encode()).hexdigest(), user=user if index % 2 == 0 else other,
        expires_at=timezone.now() + timedelta(seconds=30)) for index, key in enumerate(keys)])
    return user, other, room, keys


async def connect(key, origin=b'http://localhost:3030'):
    socket = WebsocketCommunicator(socket_application(), '/ws/community-chat/', headers=[(b'origin', origin)])
    assert (await socket.connect())[0]
    await socket.send_json_to({'ticket': key})
    return socket


@pytest.mark.django_db(transaction=True)
async def test_ticket_once_origin_and_two_users(settings, tmp_path):
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    settings.COMMUNITY_CHAT_ALLOWED_ORIGINS = ['http://localhost:3030']
    user, _, room, keys = await provision(2)
    first, second = await connect(keys[0]), await connect(keys[1])
    try:
        assert (await first.receive_json_from())['type'] == 'ready'
        assert (await second.receive_json_from())['type'] == 'ready'
        await database_sync_to_async(send_message)(user, room.pk, {'text': 'hello', 'attachments': [], 'request_key': 'socket'})
        events = await asyncio.gather(first.receive_json_from(), second.receive_json_from())
        assert events[0] == events[1] and events[0]['type'] == 'changed'
        assert 'text' not in events[0]
        replay = await connect(keys[0])
        assert (await replay.receive_output())['code'] == 4401
        await replay.disconnect()
        rejected = WebsocketCommunicator(socket_application(), '/ws/community-chat/', headers=[(b'origin', b'https://untrusted.invalid')])
        assert not (await rejected.connect())[0]
        await rejected.disconnect()
    finally:
        await first.disconnect()
        await second.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_expired_ticket_and_disabled_user(settings, tmp_path):
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    settings.COMMUNITY_CHAT_ALLOWED_ORIGINS = ['http://localhost:3030']
    user, _, _, keys = await provision(2)
    await database_sync_to_async(SocketTicket.objects.filter(digest=hashlib.sha256(keys[0].encode()).hexdigest()).update)(expires_at=timezone.now() - timedelta(seconds=1))
    socket = await connect(keys[0])
    assert (await socket.receive_output())['code'] == 4401
    await socket.disconnect()
    await database_sync_to_async(get_user_model().objects.exclude(pk=user.pk).update)(is_active=False)
    disabled = await connect(keys[1])
    assert (await disabled.receive_output())['code'] == 4401
    await disabled.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_100_connections_fanout(settings, tmp_path):
    """Repeatable in-process ASGI capacity smoke, not a network benchmark."""
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    settings.COMMUNITY_CHAT_ALLOWED_ORIGINS = ['http://localhost:3030']
    user, _, room, keys = await provision(100)
    sockets = []
    try:
        for key in keys:
            socket = await connect(key)
            assert (await socket.receive_json_from(timeout=5))['type'] == 'ready'
            sockets.append(socket)
        start = time.perf_counter()
        await database_sync_to_async(send_message)(user, room.pk, {'text': 'fanout', 'attachments': [], 'request_key': 'load'})
        async def received(socket):
            event = await socket.receive_json_from(timeout=10)
            assert event['type'] == 'changed' and event['room'] == str(room.pk)
            return (time.perf_counter() - start) * 1000
        elapsed = await asyncio.gather(*(received(socket) for socket in sockets))
        print(f'\nCommunity ASGI fanout: connections=100 delivered=100 median_ms={statistics.median(elapsed):.1f} p95_ms={sorted(elapsed)[94]:.1f} max_ms={max(elapsed):.1f}')
    finally:
        await asyncio.gather(*(socket.disconnect(timeout=10) for socket in sockets))

import asyncio
import base64
from datetime import timedelta

import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.remote_access.broker import Subscription, publish
from apps.remote_access.consumer import connector_socket
from apps.remote_access.models import RemoteDevice
from apps.remote_access.security import digest


@pytest.fixture
def connected_device(transactional_db, settings):
    settings.DEBUG = False
    settings.REMOTE_RELAY_ENABLED = True
    settings.REMOTE_RELAY_REDIS_URL = ''
    settings.REMOTE_RELAY_ALLOW_MEMORY = True
    user = get_user_model().objects.create_user(username='phone-owner')
    other = get_user_model().objects.create_user(username='other-owner')
    device = RemoteDevice.objects.create(
        name='Test Computer', owner=user, confirmed=True, token_hash=digest('computer-secret'),
        pairing_expires_at=timezone.now() + timedelta(minutes=10),
    )
    return device, str(AccessToken.for_user(user)), str(AccessToken.for_user(other))


async def connect_computer(device):
    ws = WebsocketCommunicator(connector_socket, '/ws/remote/connector/', headers=[
        (b'x-device-id', str(device.id).encode()), (b'authorization', b'Device computer-secret'),
    ])
    connected, _ = await ws.connect()
    assert connected
    assert (await ws.receive_json_from())['type'] == 'ready'
    return ws


async def frame(ws, kind, **fields):
    await ws.send_json_to({'v': 1, 'type': kind, **fields})


@pytest.mark.asyncio
@pytest.mark.parametrize('content_type,status,body', [
    ('application/json', 200, b'[{"title":"private"}]'),
    ('text/event-stream', 200, b'id: 1\ndata: {"type":"output.delta"}\n\n'),
    ('application/problem+json', 410, b'{"code":"event_history_compacted","snapshot_url":"http://127.0.0.1/api/v1/runs/run/snapshot"}'),
])
async def test_sse_bridge_ack_cancellation_and_no_server_business_records(connected_device, content_type, status, body):
    device, token, _ = connected_device
    streaming = content_type != 'application/json'
    target = ('organizations/10000000-0000-0000-0000-000000000001/'
              'runs/20000000-0000-0000-0000-000000000002/stream?after=0') if streaming else 'conversations/'
    ws = await connect_computer(device)
    try:
        response_task = asyncio.create_task(AsyncClient().get(
            f'/api/v1/remote/devices/{device.id}/proxy/{target}',
            headers={'Authorization': f'Bearer {token}',
                     'Accept': 'text/event-stream' if streaming else 'application/json'},
        ))
        request = await ws.receive_json_from(timeout=5)
        assert request['type'] == 'request'
        assert request['path'] == '/api/v1/' + target
        assert 'Authorization' not in request
        await frame(ws, 'start', id=request['id'], status=status, content_type=content_type)
        response = await response_task
        assert response.status_code == status
        assert response['Content-Type'] == content_type
        await frame(ws, 'chunk', id=request['id'], body=base64.b64encode(body).decode())
        iterator = response.streaming_content.__aiter__()
        assert await anext(iterator) == body
        next_chunk = asyncio.create_task(anext(iterator))
        ack = await ws.receive_json_from()
        assert ack['type'] == 'ack'
        await frame(ws, 'end', id=request['id'])
        with pytest.raises(StopAsyncIteration):
            await next_chunk
        assert (await ws.receive_json_from())['type'] == 'cancel'
        # Cancellation refers only to a request/subscription, not a Run command.
        await frame(ws, 'ping')
        assert (await ws.receive_json_from())['type'] == 'pong'
        from apps.conversations.models import Conversation
        from modules.execution.models import Run, IdempotencyRecord
        assert await Conversation.objects.acount() == 0
        assert await Run.objects.acount() == 0
        assert await IdempotencyRecord.objects.acount() == 0
    finally:
        await ws.disconnect()
    await device.arefresh_from_db()
    assert not device.online


@pytest.mark.asyncio
async def test_sse_accept_preserves_authentication_ownership_and_offline_checks(connected_device):
    device, token, other_token = connected_device
    client = AsyncClient()
    url = (f'/api/v1/remote/devices/{device.id}/proxy/'
           'organizations/10000000-0000-0000-0000-000000000001/'
           'runs/20000000-0000-0000-0000-000000000002/stream?after=0')
    headers = {'Accept': 'text/event-stream'}
    assert (await client.get(url, headers=headers)).status_code == 401
    assert (await client.get(url, headers={**headers, 'Authorization': f'Bearer {other_token}'})).status_code == 404
    assert (await client.get(url, headers={**headers, 'Authorization': f'Bearer {token}'})).status_code == 503


@pytest.mark.asyncio
async def test_relay_ownership_offline_allowlist_and_revoke(connected_device):
    device, token, other_token = connected_device
    client = AsyncClient()
    url = f'/api/v1/remote/devices/{device.id}/proxy/conversations/'
    assert (await client.get(url, headers={'Authorization': f'Bearer {other_token}'})).status_code == 404
    assert (await client.get(url, headers={'Authorization': f'Bearer {token}'})).status_code == 503
    ws = await connect_computer(device)
    try:
        blocked = await client.get(f'/api/v1/remote/devices/{device.id}/proxy/auth/profile/',
                                   headers={'Authorization': f'Bearer {token}'})
        assert blocked.status_code == 400
        assert await ws.receive_nothing(timeout=0.05)
        await RemoteDevice.objects.filter(pk=device.id).aupdate(revoked_at=timezone.now())
        assert (await ws.receive_json_from(timeout=3))['type'] == 'revoked'
        message = await ws.receive_output(timeout=3)
        assert message['type'] == 'websocket.close'
    finally:
        await ws.disconnect()


@pytest.mark.asyncio
async def test_socket_rejects_unconfirmed_credentials_and_browser_origin(connected_device):
    device, _, _ = connected_device
    await RemoteDevice.objects.filter(pk=device.id).aupdate(confirmed=False)
    ws = WebsocketCommunicator(connector_socket, '/ws/remote/connector/', headers=[
        (b'x-device-id', str(device.id).encode()), (b'authorization', b'Device computer-secret'),
    ])
    assert (await ws.connect())[0] is False
    await ws.disconnect()
    ws = WebsocketCommunicator(connector_socket, '/ws/remote/connector/', headers=[(b'origin', b'https://browser.example')])
    assert (await ws.connect())[0] is False
    await ws.disconnect()


@pytest.mark.asyncio
async def test_late_cancelled_response_does_not_close_other_subscriptions(connected_device):
    device, _, _ = connected_device
    ws = await connect_computer(device)
    try:
        await frame(ws, 'end', id='cancelled-request')
        await frame(ws, 'ping')
        assert (await ws.receive_json_from())['type'] == 'pong'
    finally:
        await ws.disconnect()


@pytest.mark.asyncio
async def test_pubsub_is_transient_and_bounded(settings):
    settings.DEBUG = False
    settings.REMOTE_RELAY_REDIS_URL = ''
    settings.REMOTE_RELAY_ALLOW_MEMORY = True
    assert await publish('absent', {'body': 'not queued'}) == 0
    subscription = await Subscription('slow').open()
    try:
        for _ in range(129):
            await publish('slow', {'type': 'chunk', 'body': 'x'})
        assert (await subscription.receive())['type'] == 'error'
    finally:
        await subscription.close()
    assert await publish('slow', {'body': 'not queued'}) == 0

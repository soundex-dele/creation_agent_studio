import asyncio
import base64
import json
from unittest.mock import patch

import pytest
from django.test import AsyncClient
from django.utils import timezone

from apps.remote_access import downloads
from apps.remote_access.file_protocol import FILE_CHUNK
from apps.remote_access.files import FileError, FileManager
from apps.remote_access.protocol import FILE_ROOT, MAX_CHUNK
from apps.remote_access.tests.test_relay import connected_device, connect_computer, frame  # noqa: F401
from apps.remote_access.tests.test_redis import redis_url  # noqa: F401


@pytest.fixture
def local_rpc(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / 'journal')
    async def rpc(device, owner, method, path, body=None, key=''):
        # Keep relay-side ownership checks even when replacing its transport.
        from asgiref.sync import sync_to_async
        await sync_to_async(downloads.device_for_owner)(device, owner)
        try:
            return (await manager.request(method, path, body, key))[1]
        except FileError as exc:
            raise downloads.RPCError(exc.status, exc.detail) from None
    monkeypatch.setattr(downloads, 'file_rpc', rpc)
    return manager


async def new_download(client, device, token, source, key='create'):
    return await client.post(f'/api/v1/remote/devices/{device.id}/downloads/',
                             data=json.dumps({'path': str(source)}), content_type='application/json',
                             headers={'Authorization': f'Bearer {token}', 'Idempotency-Key': key})


@pytest.mark.asyncio
async def test_cookie_native_range_stream_progress_and_cancel(connected_device, local_rpc, tmp_path):
    device, token, other = connected_device
    source = tmp_path / '中文 文件.txt'
    data = b'a' * FILE_CHUNK + b'xyz'
    source.write_bytes(data)
    client = AsyncClient()
    created = await new_download(client, device, token, source)
    assert created.status_code == 200, created.content
    item = created.json()
    url = item['download_url']
    cookie = created.cookies[downloads.COOKIE]
    assert cookie['path'] == url and cookie['httponly'] and cookie['max-age'] == 3600
    assert cookie['samesite'] == 'Strict'
    assert (await AsyncClient().get(url)).status_code == 403
    assert (await new_download(AsyncClient(), device, other, source)).status_code == 403
    # No Authorization header: native browser downloads use only the scoped cookie.
    response = await client.get(url, headers={'Range': f'bytes={FILE_CHUNK}-'})
    assert response.status_code == 206 and response['Content-Length'] == '3'
    assert response['Content-Range'] == f'bytes {FILE_CHUNK}-{len(data)-1}/{len(data)}'
    assert 'filename*=utf-8' in response['Content-Disposition']
    assert b''.join([chunk async for chunk in response.streaming_content]) == b'xyz'
    assert local_rpc.transfers[item['id']]['offset'] == 3
    response = await client.get(url, headers={'Range': f'bytes=0-{FILE_CHUNK-1}'})
    chunks = [chunk async for chunk in response.streaming_content]
    assert b''.join(chunks) == data[:FILE_CHUNK] and max(map(len, chunks)) <= FILE_CHUNK
    assert local_rpc.transfers[item['id']]['state'] == 'completed'
    invalid = await client.get(url, headers={'Range': 'bytes=0-1,4-5'})
    assert invalid.status_code == 416 and invalid['Content-Range'] == f'bytes */{len(data)}'
    head = await client.head(url)
    assert head.status_code == 200 and head['Content-Length'] == str(len(data))
    assert list(head.streaming_content) == []  # Django's test client strips HEAD bodies.
    local_rpc.cancel(local_rpc.transfers[item['id']])
    assert (await client.get(url)).status_code == 410


@pytest.mark.asyncio
async def test_cookie_scope_expiry_and_revocation(connected_device, local_rpc, tmp_path):
    device, token, _ = connected_device
    source = tmp_path / 'empty'
    source.touch()
    client = AsyncClient()
    created = await new_download(client, device, token, source)
    item = created.json()
    assert (await client.get(downloads.content_url(device.id, '0' * 32))).status_code == 403
    with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 3602):
        assert (await client.get(item['download_url'])).status_code == 403
    response = await client.get(item['download_url'])
    assert response['Content-Length'] == '0'
    assert [chunk async for chunk in response.streaming_content] == []
    assert local_rpc.transfers[item['id']]['state'] == 'completed'
    device.revoked_at = timezone.now()
    await device.asave(update_fields=['revoked_at'])
    assert (await client.get(item['download_url'])).status_code == 403


@pytest.mark.asyncio
async def test_source_change_and_slow_client_read_ahead(connected_device, local_rpc, tmp_path):
    device, token, _ = connected_device
    source = tmp_path / 'large'
    source.write_bytes(b'a' * (FILE_CHUNK * 3))
    client = AsyncClient()
    item = (await new_download(client, device, token, source)).json()
    response = await client.get(item['download_url'])
    iterator = response.streaming_content.__aiter__()
    assert len(await anext(iterator)) == FILE_CHUNK
    # A slow reader has neither acknowledged nor requested the next block.
    assert local_rpc.transfers[item['id']]['offset'] == 0
    source.write_bytes(b'new version')
    with pytest.raises(downloads.RPCError):
        await anext(iterator)
    assert local_rpc.transfers[item['id']]['state'] == 'failed'


@pytest.mark.parametrize('header,size,expected', [('', 0, (0, -1, 200)), ('bytes=-2', 10, (8, 9, 206)),
                                               ('bytes=2-100', 10, (2, 9, 206)), ('bytes=0-', 10, (0, 9, 206))])
def test_range(header, size, expected):
    assert downloads.byte_range(header, size) == expected


@pytest.mark.parametrize('header', ['bytes=-0', 'bytes=10-', 'bytes=3-2', 'bytes=1-2,4-5', 'items=0-3'])
def test_invalid_range(header):
    with pytest.raises(downloads.RPCError):
        downloads.byte_range(header, 10)


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['memory', 'redis'])
async def test_download_real_relay_bounded_ack(connected_device, settings, request, transport):
    device, _, _ = connected_device
    if transport == 'redis':
        settings.REMOTE_RELAY_REDIS_URL = request.getfixturevalue('redis_url')
    ws = await connect_computer(device)
    try:
        task = asyncio.create_task(downloads.file_rpc(device.id, device.owner_id, 'GET', FILE_ROOT + 'roots/'))
        message = await ws.receive_json_from(timeout=5)
        rid = message['id']
        await frame(ws, 'start', id=rid, status=200, content_type='application/json')
        payload = json.dumps({'data': 'a' * FILE_CHUNK}).encode()
        for offset in range(0, len(payload), MAX_CHUNK):
            await frame(ws, 'chunk', id=rid, body=base64.b64encode(payload[offset:offset + MAX_CHUNK]).decode())
            assert (await ws.receive_json_from(timeout=5))['type'] == 'ack'
        await frame(ws, 'end', id=rid)
        assert len((await task)['data']) == FILE_CHUNK
        assert (await ws.receive_json_from())['type'] == 'cancel'
    finally:
        await ws.disconnect()

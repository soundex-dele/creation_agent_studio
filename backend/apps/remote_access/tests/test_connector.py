import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.remote_access import connector
from apps.remote_access.security import encrypt_credentials
from modules.execution.infrastructure.coordinator_lock import CoordinatorAlreadyRunning, CoordinatorFileLock


class Socket:
    def __init__(self):
        self.input = asyncio.Queue()
        self.output = asyncio.Queue()

    async def send(self, raw):
        await self.output.put(json.loads(raw))

    async def __aiter__(self):
        while True:
            yield json.dumps(await self.input.get())


class TwoChunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'first'
        yield b'second'


@pytest.mark.asyncio
async def test_connector_streams_with_credit_and_preserves_local_credentials(settings, monkeypatch):
    settings.REMOTE_CONNECTOR_LOCAL_URL = 'http://127.0.0.1:8080'
    config = SimpleNamespace(server_url='https://relay.example', device_id='device', computer_name='Computer',
                             credentials=encrypt_credentials({'local_token': 'local-only', 'device_token': 'relay-only'}),
                             organization_id='10000000-0000-0000-0000-000000000001', enabled=True, revision=1)
    socket = Socket()
    local_requests = []

    async def local_http(request):
        local_requests.append(request)
        if request.url.path == '/healthz/':
            return httpx.Response(200, json={'ok': True})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=TwoChunks())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(connector.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(local_http), **kwargs))

    @asynccontextmanager
    async def connect(url, **kwargs):
        assert url == 'wss://relay.example/ws/remote/connector/'
        assert kwargs['additional_headers']['Authorization'] == 'Device relay-only'
        assert 'local-only' not in str(kwargs)
        yield socket

    monkeypatch.setattr(connector, 'connect', connect)
    monkeypatch.setattr(connector, 'read_config', AsyncMock(return_value=config))
    monkeypatch.setattr(connector, 'report', AsyncMock())
    running = asyncio.create_task(connector.run_connection(config))
    try:
        await socket.input.put({'v': 1, 'type': 'ready'})
        request_id = 'a' * 32
        await socket.input.put({'v': 1, 'type': 'request', 'id': request_id, 'method': 'GET',
                                'path': '/api/v1/conversations/', 'body': None})
        messages = []
        while not messages or messages[-1]['type'] != 'chunk':
            messages.append(await asyncio.wait_for(socket.output.get(), 2))
        assert any(item['type'] == 'start' for item in messages)
        await asyncio.sleep(0.03)
        assert socket.output.empty()  # No second body until the phone consumes the first.
        await socket.input.put({'v': 1, 'type': 'ack', 'id': request_id})
        assert (await asyncio.wait_for(socket.output.get(), 2))['type'] == 'chunk'
        await socket.input.put({'v': 1, 'type': 'cancel', 'id': request_id})
        await asyncio.sleep(0.03)
        request = next(item for item in local_requests if item.url.path != '/healthz/')
        assert request.headers['authorization'] == 'RemoteLocal local-only'
        assert request.headers['x-organization-id'] == config.organization_id
        assert 'relay-only' not in str(request.headers)
        assert not any(item.url.path.endswith('/commands') for item in local_requests)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_connector_detects_saved_enable_without_backend_restart(monkeypatch):
    disabled = SimpleNamespace(enabled=False, device_id=None, bound_account='')
    enabled = SimpleNamespace(enabled=True, device_id='device', bound_account='account', revision=1)
    read = AsyncMock(side_effect=[disabled, enabled])
    connect = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(connector, 'read_config', read)
    monkeypatch.setattr(connector, 'run_connection', connect)
    monkeypatch.setattr(connector, 'report', AsyncMock())
    monkeypatch.setattr(connector.asyncio, 'sleep', AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        await connector.run_connector()
    connect.assert_awaited_once_with(enabled)


def test_single_instance_lock_released_on_exit(tmp_path):
    first = CoordinatorFileLock(tmp_path / 'remote')
    second = CoordinatorFileLock(tmp_path / 'remote')
    with first:
        with pytest.raises(CoordinatorAlreadyRunning):
            second.acquire()
    with second:
        pass


def test_connector_refuses_non_loopback_api(settings):
    settings.REMOTE_CONNECTOR_LOCAL_URL = 'http://external.example'
    with pytest.raises(ValueError):
        connector.local_origin()

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, ANY

import httpx
import pytest

from apps.remote_access import connector
from apps.remote_access.security import encrypt_credentials
from apps.remote_access.terminals import TerminalManager
from .test_terminals import FakeProcess
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
    connect.assert_awaited_once_with(enabled, ANY, ANY)


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


@pytest.mark.asyncio
async def test_terminal_dispatch_rechecks_local_permission_and_preserves_sessions_on_disconnect(settings, monkeypatch):
    settings.REMOTE_CONNECTOR_LOCAL_URL = 'http://127.0.0.1:8080'
    allowed = False
    config = SimpleNamespace(server_url='https://relay.example', device_id='device', computer_name='Computer',
                             credentials=encrypt_credentials({'local_token': 'local-only', 'device_token': 'relay-only'}),
                             organization_id='10000000-0000-0000-0000-000000000001', enabled=True, revision=1)
    socket = Socket()
    local_requests = []
    async def local_http(request):
        local_requests.append(request)
        return httpx.Response(200, json={'terminal': {'enabled': allowed, 'supported': True}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(connector.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(local_http), **kwargs))
    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield socket
    monkeypatch.setattr(connector, 'connect', connect)
    monkeypatch.setattr(connector, 'read_config', AsyncMock(return_value=config))
    monkeypatch.setattr(connector, 'report', AsyncMock())
    manager = TerminalManager(FakeProcess)
    running = asyncio.create_task(connector.run_connection(config, manager))
    async def request(key):
        await socket.input.put({'v': 1, 'type': 'request', 'id': key * 32, 'method': 'POST',
                                'path': '/api/v1/remote-access/terminals/', 'body': {'cols': 80, 'rows': 24},
                                'idempotency_key': key})
        status, body = None, b''
        while True:
            message = await asyncio.wait_for(socket.output.get(), 3)
            if message.get('id') != key * 32:
                continue
            if message['type'] == 'start':
                status = message['status']
            elif message['type'] == 'chunk':
                body += base64.b64decode(message['body'])
                await socket.input.put({'v': 1, 'type': 'ack', 'id': key * 32})
            elif message['type'] == 'end':
                return status, json.loads(body)
    try:
        assert (await request('a'))[0] == 403
        assert not manager.sessions
        allowed = True
        status, result = await request('b')
        assert status == 201
        assert result['id'] in manager.sessions
        assert all(r.url.path in {'/healthz/', '/api/v1/remote-access/context/'} for r in local_requests)
        checks = [r for r in local_requests if r.url.path.endswith('/context/')]
        assert len(checks) == 2
        assert all(r.headers['authorization'] == 'RemoteLocal local-only' for r in checks)
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        assert not manager.sessions[result['id']].process.closed
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await manager.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['file-disabled', 'host-disabled', 'license-denied', 'host-stopped', 'grant-changed', 'unbind'])
async def test_file_monitor_cleans_up_without_relay_connection(settings, monkeypatch, tmp_path, change):
    from apps.remote_access.files import FileManager
    from .test_files import create
    settings.REMOTE_CONNECTOR_LOCAL_URL = 'http://127.0.0.1:8080'
    config = SimpleNamespace(device_id='device', credentials=encrypt_credentials({'local_token': 'local'}),
                             local_user_id=1, organization_id='org', enabled=True, bound_account='user', file_transfer_enabled=True)
    manager = FileManager(tmp_path / 'journal')
    manager.grant = (config.device_id, config.credentials, config.local_user_id, config.organization_id)
    create(manager, tmp_path, 1)
    if change == 'file-disabled': config.file_transfer_enabled = False
    if change == 'host-disabled': config.enabled = False
    if change == 'grant-changed': config.local_user_id = 2
    if change == 'unbind': config.bound_account = ''
    async def local_http(request):
        if change == 'host-stopped': raise httpx.ConnectError('stopped')
        return httpx.Response(403 if change == 'license-denied' else 200, json={'files': {'enabled': True}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(connector.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(local_http), **kwargs))
    monkeypatch.setattr(connector, 'read_config', AsyncMock(return_value=config))
    monitor = asyncio.create_task(connector.monitor_files(manager))
    try:
        for _ in range(100):
            if not manager.transfers: break
            await asyncio.sleep(.02)
        assert not manager.transfers
        assert not list(tmp_path.glob('.agent-studio-upload-*.part'))
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        await manager.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['terminal-disabled', 'host-disabled', 'license-denied', 'host-stopped', 'grant-changed'])
async def test_terminal_monitor_cleans_up_without_relay_connection(settings, monkeypatch, change):
    settings.REMOTE_CONNECTOR_LOCAL_URL = 'http://127.0.0.1:8080'
    config = SimpleNamespace(device_id='device', credentials=encrypt_credentials({'local_token': 'local'}),
                             local_user_id=1, organization_id='org', enabled=True, bound_account='user', terminal_enabled=True)
    manager = TerminalManager(FakeProcess)
    manager.grant = (config.device_id, config.credentials, config.local_user_id, config.organization_id)
    from .test_terminals import create
    session = await create(manager)
    if change == 'terminal-disabled': config.terminal_enabled = False
    if change == 'host-disabled': config.enabled = False
    if change == 'grant-changed': config.local_user_id = 2
    async def local_http(request):
        if change == 'host-stopped': raise httpx.ConnectError('stopped')
        return httpx.Response(403 if change == 'license-denied' else 200,
                              json={'terminal': {'enabled': True}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(connector.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(local_http), **kwargs))
    monkeypatch.setattr(connector, 'read_config', AsyncMock(return_value=config))
    monitor = asyncio.create_task(connector.monitor_terminals(manager))
    try:
        await asyncio.wait_for(session.reader, 3)
        assert session.process.closed and not manager.sessions
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        await manager.close_all()

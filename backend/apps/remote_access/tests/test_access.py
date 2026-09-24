from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.enterprise.models import Membership
from apps.remote_access.models import LocalRemoteConfig, RemoteDevice
from apps.remote_access.protocol import validate_request
from apps.remote_access.security import decrypt_credentials, digest, encrypt_credentials


def test_remote_allows_execution_settings_and_structured_answers():
    path = "/api/v1/conversations/1/send_message/"
    assert validate_request("POST", path, {
        "content": "Plan a change", "permission_mode": "allow_all", "collaboration_mode": "plan",
    }) == path
    command_path = "/api/v1/runs/10000000-0000-0000-0000-000000000001/commands"
    for command in ("answer", "grant_permission", "deny_permission"):
        assert validate_request("POST", command_path, {
            "type": command, "input_request_id": "question-1", "idempotency_key": "answer-1",
            "payload": {"answers": {"framework": {"answers": ["React"]}}},
        }) == command_path
    with pytest.raises(ValueError):
        validate_request("POST", path, {"content": "hello", "sandbox": "danger-full-access"})


@pytest.fixture
def grant(db, settings, tmp_path):
    settings.REMOTE_ACCESS_HOST_ENABLED = True
    settings.REMOTE_RELAY_ENABLED = True
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    cache.clear()
    user = get_user_model().objects.create_user(username="local-owner", password="test", role="admin")
    organization = user.owned_organizations.get()
    config = LocalRemoteConfig.objects.create(
        enabled=True, local_user=user, organization=organization,
        server_url="https://relay.example", bound_account="phone-owner",
        credentials=encrypt_credentials({"device_token": "device-secret", "local_token": "local-secret"}),
    )
    return user, organization, config


def test_local_settings_persist_and_never_expose_credentials(grant):
    user, org, config = grant
    client = APIClient()
    client.force_authenticate(user)
    result = client.put('/api/v1/remote-access/', {
        'enabled': False, 'computer_name': '书房电脑', 'server_url': 'https://relay.example/',
        'local_user_id': user.id, 'organization_id': str(org.id),
    }, format='json')
    assert result.status_code == 200, result.data
    assert result.data['computer_name'] == '书房电脑'
    assert 'credentials' not in result.data
    assert 'secret' not in result.content.decode()
    config.refresh_from_db()
    assert not config.enabled
    assert config.bound_account == 'phone-owner'
    assert config.revision == 1
    assert decrypt_credentials(config.credentials)['local_token'] == 'local-secret'
    assert APIClient().get('/api/v1/remote-access/').status_code in {401, 403}


def test_terminal_opt_in_preserves_legacy_updates_and_requires_admin(grant):
    user, org, config = grant
    assert config.terminal_enabled is False
    client = APIClient()
    client.force_authenticate(user)
    payload = {'enabled': True, 'computer_name': '书房电脑', 'server_url': 'https://relay.example',
               'local_user_id': user.id, 'organization_id': str(org.id)}
    response = client.put('/api/v1/remote-access/', {**payload, 'terminal_enabled': True}, format='json')
    assert response.status_code == 200
    assert response.data['terminal_enabled'] is True
    assert client.put('/api/v1/remote-access/', payload, format='json').data['terminal_enabled'] is True
    remote = APIClient()
    remote.credentials(HTTP_AUTHORIZATION='RemoteLocal local-secret')
    assert remote.get('/api/v1/remote-access/context/').data['terminal']['enabled'] is True
    assert remote.put('/api/v1/remote-access/', {**payload, 'terminal_enabled': False}, format='json').status_code == 403
    user.role = 'member'
    user.save()
    assert client.put('/api/v1/remote-access/', {**payload, 'terminal_enabled': False}, format='json').status_code == 403


def test_file_opt_in_independent_from_terminal_and_legacy_updates(grant):
    user, org, config = grant
    assert not config.file_transfer_enabled and not config.terminal_enabled
    client = APIClient()
    client.force_authenticate(user)
    payload = {'enabled': True, 'computer_name': '文件测试电脑', 'server_url': 'https://relay.example',
               'local_user_id': user.id, 'organization_id': str(org.id)}
    response = client.put('/api/v1/remote-access/', {**payload, 'file_transfer_enabled': True}, format='json')
    assert response.status_code == 200
    assert response.data['file_transfer_enabled'] and not response.data['terminal_enabled']
    assert client.put('/api/v1/remote-access/', payload, format='json').data['file_transfer_enabled']
    remote = APIClient()
    remote.credentials(HTTP_AUTHORIZATION='RemoteLocal local-secret')
    capability = remote.get('/api/v1/remote-access/context/').data['files']
    assert capability == {'supported': True, 'enabled': True, 'max_file_size': 2147483648, 'chunk_size': 262144}
    assert remote.put('/api/v1/remote-access/', {**payload, 'file_transfer_enabled': False}, format='json').status_code == 403
    user.role = 'member'
    user.save()
    assert client.put('/api/v1/remote-access/', {**payload, 'file_transfer_enabled': False}, format='json').status_code == 403


def test_server_capability_hidden_and_non_admin_cannot_configure(grant, settings):
    user, _, _ = grant
    client = APIClient()
    client.force_authenticate(user)
    settings.REMOTE_ACCESS_HOST_ENABLED = False
    assert client.get('/api/v1/remote-access/').data == {'host_enabled': False, 'manageable': False}
    assert client.post('/api/v1/remote-access/pair/').status_code == 404
    settings.REMOTE_ACCESS_HOST_ENABLED = True
    user.role = 'member'
    user.save()
    assert client.post('/api/v1/remote-access/reconnect/').status_code == 403


def test_local_credential_uses_grant_and_checks_revocation_license_and_loopback(grant):
    user, org, config = grant
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='RemoteLocal local-secret')
    response = client.get('/api/v1/remote-access/context/', HTTP_X_ORGANIZATION_ID='wrong')
    assert response.status_code == 200, response.data
    assert response.data['organization_id'] == str(org.id)
    assert client.get('/api/v1/remote-access/context/', REMOTE_ADDR='192.168.1.2').status_code in {401, 403}
    assert client.get('/api/v1/remote-access/').status_code == 403
    assert client.get('/api/v1/conversations/?organization_id=other').status_code == 403
    with patch('apps.remote_access.security._require_active_license', side_effect=__import__('rest_framework').exceptions.AuthenticationFailed('expired')):
        assert client.get('/api/v1/conversations/').status_code in {401, 403}
    Membership.objects.filter(user=user, organization=org).update(is_active=False)
    assert client.get('/api/v1/conversations/').status_code == 403
    Membership.objects.filter(user=user, organization=org).update(is_active=True)
    config.enabled = False
    config.save()
    assert client.get('/api/v1/conversations/').status_code in {401, 403}


def test_create_conversation_replays_and_rejects_changed_payload(grant):
    user, _, _ = grant
    client = APIClient()
    client.force_authenticate(user)
    first = client.post('/api/v1/conversations/', {'title': 'hello'}, format='json', HTTP_IDEMPOTENCY_KEY='same-create')
    assert first.status_code == 201, first.data
    second = client.post('/api/v1/conversations/', {'title': 'hello'}, format='json', HTTP_IDEMPOTENCY_KEY='same-create')
    assert second.status_code == 201
    assert second.data['id'] == first.data['id']
    assert second['Idempotent-Replay'] == 'true'
    conflict = client.post('/api/v1/conversations/', {'title': 'changed'}, format='json', HTTP_IDEMPOTENCY_KEY='same-create')
    assert conflict.status_code == 409
    assert user.conversations.count() == 1


def test_history_pages_preserve_local_user_scope(grant):
    from apps.conversations.models import Conversation
    user, org, _ = grant
    Conversation.objects.bulk_create([Conversation(user=user, organization=org, title=f'chat-{index}') for index in range(25)])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='RemoteLocal local-secret')
    first = client.get('/api/v1/conversations/?page=1', HTTP_X_ORGANIZATION_ID='wrong')
    second = client.get('/api/v1/conversations/?page=2')
    assert first.status_code == second.status_code == 200
    assert len(first.data['results']) == 20
    assert len(second.data['results']) == 5
    assert not set(item['id'] for item in first.data['results']) & set(item['id'] for item in second.data['results'])


def test_remote_catalog_is_limited_to_explicitly_authorized_organization(grant):
    from apps.agents.models import Agent, AgentCategory
    from apps.applications.models import Application, ApplicationCategory
    user, org, _ = grant
    other_user = get_user_model().objects.create_user(username='other-organization')
    other_org = other_user.owned_organizations.get()
    agent_category = AgentCategory.objects.create(name='Remote agents', slug='remote-agents')
    app_category = ApplicationCategory.objects.create(name='Remote apps', slug='remote-apps')
    for organization, name in [(org, 'allowed'), (other_org, 'outside')]:
        Agent.objects.create(name=name, slug=name, category=agent_category, created_by=user, organization=organization)
        Application.objects.create(name=name, slug=name, category=app_category, created_by=user, organization=organization, kind='chat')
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='RemoteLocal local-secret')
    agents = client.get('/api/v1/agents/')
    apps = client.get('/api/v1/apps/?kind=chat')
    assert agents.status_code == apps.status_code == 200
    assert {item['name'] for item in agents.data['results']} == {'allowed'}
    assert {item['name'] for item in apps.data['results']} == {'allowed'}


def test_pairing_requires_local_confirmation_and_is_single_use(grant):
    user, _, _ = grant
    public = APIClient()
    created = public.post('/api/v1/remote/pairings/', {
        'name': 'Computer', 'code': 'ABCDEFGH', 'token': 'a' * 48,
    }, format='json')
    assert created.status_code == 201, created.data
    device_id = created.data['id']
    owner = APIClient()
    owner.force_authenticate(user)
    claimed = owner.post('/api/v1/remote/claim/', {'code': 'ABCD-EFGH'}, format='json')
    assert claimed.status_code == 200
    assert owner.get('/api/v1/remote/devices/').data[0]['confirmed'] is False
    assert owner.post('/api/v1/remote/claim/', {'code': 'ABCDEFGH'}, format='json').status_code == 400
    computer = APIClient()
    computer.credentials(HTTP_AUTHORIZATION='Device ' + 'a' * 48)
    assert computer.get(f'/api/v1/remote/connector/{device_id}/').data['account'] == user.username
    assert computer.post(f'/api/v1/remote/connector/{device_id}/', {'action': 'confirm', 'account_id': user.id + 1}, format='json').status_code == 400
    assert computer.post(f'/api/v1/remote/connector/{device_id}/', {'action': 'confirm', 'account_id': user.id}, format='json').status_code == 200
    outsider = get_user_model().objects.create_user(username='outsider')
    other = APIClient()
    other.force_authenticate(outsider)
    assert other.get('/api/v1/remote/devices/').data == []
    assert other.delete(f'/api/v1/remote/devices/{device_id}/').status_code == 404
    assert owner.delete(f'/api/v1/remote/devices/{device_id}/').status_code == 204
    assert computer.get(f'/api/v1/remote/connector/{device_id}/').status_code == 401
    device = RemoteDevice.objects.get(pk=device_id)
    assert device.token_hash == digest('a' * 48)
    assert device.revoked_at


@pytest.mark.django_db(transaction=True)
def test_local_pairing_allows_connector_heartbeat_during_relay_request(grant, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4

    from django.db import connections

    user, _, config = grant
    config.bound_account = ''
    config.save()
    device_id = uuid4()
    seen_at = timezone.now()

    def heartbeat():
        try:
            LocalRemoteConfig.objects.filter(pk=1).update(
                connector_seen_at=seen_at, status='unpaired',
            )
        finally:
            connections.close_all()

    def relay_request(*args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(heartbeat).result(timeout=10)
        return httpx.Response(201, json={'id': str(device_id), 'expires_in': 600})

    monkeypatch.setattr('apps.remote_access.views.httpx.request', relay_request)
    client = APIClient()
    client.force_authenticate(user)
    response = client.post('/api/v1/remote-access/pair/', {}, format='json')
    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert config.device_id == device_id
    assert len(config.pairing_code) == 8
    assert config.revision == 1
    assert config.connector_seen_at == seen_at
    assert config.status == 'unpaired'


def test_local_pairing_does_not_overwrite_concurrent_settings_change(grant, monkeypatch):
    from uuid import uuid4

    user, _, config = grant
    config.bound_account = ''
    config.save()
    original_credentials = config.credentials

    def relay_request(*args, **kwargs):
        LocalRemoteConfig.objects.filter(pk=1).update(enabled=False, revision=1)
        return httpx.Response(201, json={'id': str(uuid4()), 'expires_in': 600})

    monkeypatch.setattr('apps.remote_access.views.httpx.request', relay_request)
    client = APIClient()
    client.force_authenticate(user)
    response = client.post('/api/v1/remote-access/pair/', {}, format='json')
    assert response.status_code == 409
    config.refresh_from_db()
    assert config.enabled is False
    assert config.revision == 1
    assert config.device_id is None
    assert config.pairing_code == ''
    assert config.credentials == original_credentials


@pytest.mark.parametrize('failure', [503, 'network'])
def test_local_pairing_failure_keeps_original_configuration(grant, monkeypatch, failure):
    user, _, config = grant
    config.bound_account = ''
    config.save()
    original_credentials = config.credentials

    def relay_request(*args, **kwargs):
        if failure == 'network':
            raise httpx.ConnectError('unavailable')
        return httpx.Response(failure, json={'detail': 'unavailable'})

    monkeypatch.setattr('apps.remote_access.views.httpx.request', relay_request)
    client = APIClient()
    client.force_authenticate(user)
    response = client.post('/api/v1/remote-access/pair/', {}, format='json')
    assert response.status_code == 400
    config.refresh_from_db()
    assert config.device_id is None
    assert config.pairing_code == ''
    assert config.revision == 0
    assert config.credentials == original_credentials


def test_account_can_bind_multiple_named_computers_and_revoke_one(grant):
    user, _, _ = grant
    owner = APIClient()
    owner.force_authenticate(user)
    device_ids = []
    names = ['书房电脑', '办公室电脑']
    for name, code, token in zip(names, ['ABCDEFGH', 'JKLMNPQR'], ['a' * 48, 'b' * 48]):
        computer = APIClient()
        created = computer.post('/api/v1/remote/pairings/', {
            'name': name, 'code': code, 'token': token,
        }, format='json')
        assert created.status_code == 201
        device_id = created.data['id']
        device_ids.append(device_id)
        claimed = owner.post('/api/v1/remote/claim/', {'code': code}, format='json')
        assert claimed.status_code == 200
        assert claimed.data['name'] == name
        computer.credentials(HTTP_AUTHORIZATION=f'Device {token}')
        assert computer.post(f'/api/v1/remote/connector/{device_id}/', {
            'action': 'confirm', 'account_id': user.id,
        }, format='json').status_code == 200

    devices = owner.get('/api/v1/remote/devices/').data
    assert {item['id']: item['name'] for item in devices} == dict(zip(device_ids, names))
    assert all(item['confirmed'] for item in devices)
    assert owner.delete(f'/api/v1/remote/devices/{device_ids[0]}/').status_code == 204
    remaining = owner.get('/api/v1/remote/devices/').data
    assert [item['id'] for item in remaining] == [device_ids[1]]
    computer = APIClient()
    computer.credentials(HTTP_AUTHORIZATION='Device ' + 'b' * 48)
    assert computer.get(f'/api/v1/remote/connector/{device_ids[1]}/').status_code == 200


def test_new_local_config_uses_computer_hostname(grant):
    user, _, config = grant
    config.delete()
    client = APIClient()
    client.force_authenticate(user)
    with patch('apps.remote_access.models.socket.gethostname', return_value='OFFICE-PC'):
        response = client.get('/api/v1/remote-access/')
    assert response.status_code == 200
    assert response.data['computer_name'] == 'OFFICE-PC'
    assert LocalRemoteConfig.objects.get(pk=1).computer_name == 'OFFICE-PC'


def test_expired_pairing_cannot_be_claimed_or_confirmed(grant):
    user, _, _ = grant
    device = RemoteDevice.objects.create(name='Expired', token_hash=digest('secret'), pairing_hash=digest('ABCDEFGH'),
                                         pairing_expires_at=timezone.now() - timedelta(seconds=1))
    client = APIClient()
    client.force_authenticate(user)
    assert client.post('/api/v1/remote/claim/', {'code': 'ABCDEFGH'}, format='json').status_code == 400
    client.force_authenticate(None)
    client.credentials(HTTP_AUTHORIZATION='Device secret')
    assert client.post(f'/api/v1/remote/connector/{device.id}/', {'action': 'confirm', 'account_id': user.id}, format='json').status_code == 401


@pytest.mark.parametrize('state', ['active', 'revoked', 'expired', 'missing'])
def test_local_unbind_clears_active_or_already_invalid_binding(grant, monkeypatch, state):
    user, _, config = grant
    device = RemoteDevice.objects.create(
        name='Computer', owner=user, token_hash=digest('device-secret'),
        confirmed=state != 'expired',
        pairing_expires_at=timezone.now() - timedelta(minutes=1),
        revoked_at=timezone.now() if state == 'revoked' else None,
    )
    config.device_id = device.id
    config.save()
    if state == 'missing':
        device.delete()

    # Exercise the real device-control endpoint across the HTTP boundary so
    # DRF's exception status handling is included in the local unbind result.
    def relay_request(method, url, *, json, headers, **kwargs):
        relay = APIClient()
        relay.credentials(HTTP_AUTHORIZATION=headers['Authorization'])
        response = relay.post(urlsplit(url).path, json, format='json')
        return httpx.Response(response.status_code, json=response.data, headers=dict(response.items()))

    monkeypatch.setattr('apps.remote_access.views.httpx.request', relay_request)
    local = APIClient()
    local.force_authenticate(user)
    response = local.post('/api/v1/remote-access/unbind/', {}, format='json')
    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert config.enabled is False
    assert config.status == 'disabled'
    assert config.device_id is None
    assert config.credentials == config.bound_account == config.pairing_code == ''
    if state == 'active':
        device.refresh_from_db()
        assert device.revoked_at is not None
        assert not device.online
    assert local.post('/api/v1/remote-access/unbind/', {}, format='json').status_code == 200


@pytest.mark.parametrize('failure', [403, 503, 'network'])
def test_unbind_keeps_credentials_for_retry_on_unconfirmed_failure(grant, monkeypatch, failure):
    import uuid
    user, _, config = grant
    config.device_id = uuid.uuid4()
    config.save()
    original_id, original_credentials = config.device_id, config.credentials

    def failed_request(*args, **kwargs):
        if failure == 'network':
            raise httpx.ConnectError('unavailable')
        return httpx.Response(failure, json={'detail': 'unavailable'})

    monkeypatch.setattr('apps.remote_access.views.httpx.request', failed_request)
    local = APIClient()
    local.force_authenticate(user)
    response = local.post('/api/v1/remote-access/unbind/', {}, format='json')
    assert response.status_code == 503
    config.refresh_from_db()
    assert not config.enabled
    assert config.status == 'disabled'
    assert config.device_id == original_id
    assert config.credentials == original_credentials


def test_invalid_device_credential_returns_401_with_device_challenge(grant):
    user, _, _ = grant
    device = RemoteDevice.objects.create(
        name='Computer', owner=user, confirmed=True, token_hash=digest('correct-token'),
        pairing_expires_at=timezone.now() + timedelta(minutes=10),
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Device wrong-token')
    for response in (
        client.get(f'/api/v1/remote/connector/{device.id}/'),
        client.post(f'/api/v1/remote/connector/{device.id}/', {'action': 'revoke'}, format='json'),
    ):
        assert response.status_code == 401
        assert response['WWW-Authenticate'].startswith('Device ')
    device.refresh_from_db()
    assert device.revoked_at is None


@pytest.mark.parametrize('method,path,body', [
    ('GET', 'https://evil.test/api/v1/conversations/', None),
    ('GET', '//evil.test/api/v1/conversations/', None),
    ('GET', '/api/v1/conversations/%2e%2e/auth/', None),
    ('GET', '/api/v1/conversations/1/workspace-files/', None),
    ('POST', '/api/v1/conversations/1/open-workspace/', {}),
    ('POST', '/api/v1/conversations/1/send_message/', {'content': 'x', 'images': []}),
    ('POST', '/api/v1/conversations/', {'working_directory': '/etc'}),
    ('GET', '/api/v1/agents/?organization_id=other', None),
    ('DELETE', '/api/v1/conversations/1/', None),
])
def test_allowlist_denies_unsafe_requests(method, path, body):
    with pytest.raises(ValueError):
        validate_request(method, path, body)


def test_allowlist_binds_organization_and_limits_commands():
    validate_request('GET', '/api/v1/conversations/?search=%E4%B8%AD%E6%96%87')
    org = '10000000-0000-0000-0000-000000000001'
    run = '20000000-0000-0000-0000-000000000002'
    path = f'/api/v1/organizations/{org}/runs/{run}/commands'
    validate_request('POST', path, {'type': 'answer', 'payload': {}}, org)
    with pytest.raises(ValueError):
        validate_request('POST', path, {'type': 'answer'}, 'other')
    with pytest.raises(ValueError):
        validate_request('POST', path, {'type': 'retry'}, org)

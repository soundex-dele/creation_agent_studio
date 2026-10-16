from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import close_old_connections
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from ..checks import channel_configuration
from ..media import object_path
from ..models import Attachment, Membership, Message, Room
from ..services import MAX_BYTES, send_message

ROOT = '/api/v1/community-chat/'


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.COMMUNITY_CHAT_ROOT = tmp_path / 'files'
    settings.AGENT_WORKSPACE_ROOT = tmp_path / 'users'
    users = [get_user_model().objects.create_user(username=f'chat-{i}') for i in range(3)]
    client = APIClient()
    client.force_authenticate(users[0])
    lobby = client.get(ROOT + 'rooms/').data[0]['id']
    return client, users, lobby


def send(client, room_id, key='key', text='你好', attachments=None, expected=201):
    result = client.post(ROOT + f'rooms/{room_id}/messages/', {'text': text, 'request_key': key, 'attachments': attachments or []}, format='json')
    assert result.status_code == expected, result.data
    return result.data


def group(client, users):
    result = client.post(ROOT + 'rooms/', {'kind': 'group', 'name': '伙伴', 'user_ids': [users[1].pk]}, format='json')
    assert result.status_code == 201, result.data
    return result.data['id']


def action(client, room_id, operation, expected=200, **extra):
    response = client.patch(ROOT + f'rooms/{room_id}/', {'action': operation, **extra}, format='json')
    assert response.status_code == expected, response.data
    return response


def upload(client, room_id, name='report.txt', body=b'hello'):
    result = client.post(ROOT + f'rooms/{room_id}/uploads/', {'file': SimpleUploadedFile(name, body)}, format='multipart')
    assert result.status_code == 201, result.data
    return result.data


def access(client, attachment_id, preview=False):
    return client.post(ROOT + f'attachments/{attachment_id}/access/', {'preview': preview}, format='json')


def test_lobby_cross_organization_and_public_profile(ctx):
    client, users, lobby = ctx
    assert users[0].owned_organizations.get().pk != users[1].owned_organizations.get().pk
    value = send(client, lobby)
    client.force_authenticate(users[1])
    assert client.get(ROOT + 'rooms/').data[0]['id'] == lobby
    data = client.get(ROOT + f'rooms/{lobby}/messages/').data
    assert data['messages'][0]['id'] == value['id']
    assert set(data['messages'][0]['author']) == {'id', 'username', 'nickname', 'avatar'}
    client.force_authenticate(None)
    assert client.get(ROOT + 'rooms/').status_code in {401, 403}


def test_direct_unique_and_private(ctx):
    client, users, _ = ctx
    data = {'kind': 'direct', 'user_ids': [users[1].pk]}
    first = client.post(ROOT + 'rooms/', data, format='json').data
    client.force_authenticate(users[1])
    second = client.post(ROOT + 'rooms/', {'kind': 'direct', 'user_ids': [users[0].pk]}, format='json').data
    assert first['id'] == second['id']
    client.force_authenticate(users[2])
    assert client.get(ROOT + f"rooms/{first['id']}/messages/").status_code == 403
    send(client, first['id'], expected=403)


def test_idempotency_payload_conflict_and_validation(ctx):
    client, _, lobby = ctx
    first = send(client, lobby)
    assert send(client, lobby)['id'] == first['id']
    send(client, lobby, text='different', expected=409)
    assert send(client, lobby, key='new')['id'] != first['id']
    send(client, lobby, key='empty', text='  ', expected=400)
    send(client, lobby, key='long', text='x' * 10001, expected=400)


def test_pagination_and_incremental_withdrawal(ctx):
    client, users, lobby = ctx
    for index in range(55):
        send(client, lobby, key=str(index), text=str(index))
    tail = client.get(ROOT + f'rooms/{lobby}/messages/').data
    assert len(tail['messages']) == 50 and tail['has_more']
    before = tail['messages'][0]['id']
    older = client.get(ROOT + f'rooms/{lobby}/messages/', {'before': before}).data
    assert len(older['messages']) == 5 and not older['has_more']
    target = older['messages'][0]['id']
    result = client.post(ROOT + f'rooms/{lobby}/messages/{target}/withdraw/')
    assert result.status_code == 200 and result.data['text'] == ''
    delta = client.get(ROOT + f'rooms/{lobby}/messages/', {'after_revision': tail['revision']}).data
    assert [m['id'] for m in delta['messages']] == [target]
    assert delta['messages'][0]['withdrawn'] and delta['messages'][0]['attachments'] == []
    client.force_authenticate(users[1])
    assert client.post(ROOT + f'rooms/{lobby}/messages/{target}/withdraw/').status_code == 404


def test_withdraw_time_limit_and_read_monotonicity(ctx):
    client, users, lobby = ctx
    first = send(client, lobby)
    second = send(client, lobby, key='2')
    Message.objects.filter(pk=first['id']).update(created_at=timezone.now() - timedelta(seconds=121))
    assert client.post(ROOT + f"rooms/{lobby}/messages/{first['id']}/withdraw/").status_code == 400
    client.force_authenticate(users[1])
    assert client.get(ROOT + 'rooms/').data[0]['unread'] == 2
    for item in [second, first]:
        result = client.post(ROOT + f'rooms/{lobby}/read/', {'message_id': item['id']}, format='json')
        assert result.data['last_read_id'] == second['id']
    assert client.get(ROOT + 'rooms/').data[0]['unread'] == 0


def test_group_history_and_management_permissions(ctx):
    client, users, _ = ctx
    room_id = group(client, users)
    old = send(client, room_id)
    action(client, room_id, 'leave', expected=400)
    action(client, room_id, 'rename', name='新名字')
    action(client, room_id, 'add', user_id=users[2].pk)
    client.force_authenticate(users[2])
    assert client.get(ROOT + f'rooms/{room_id}/messages/').data['messages'][0]['id'] == old['id']
    action(client, room_id, 'remove', user_id=users[1].pk, expected=403)
    action(client, room_id, 'leave')
    assert client.get(ROOT + f'rooms/{room_id}/').status_code == 403
    client.force_authenticate(users[0])
    action(client, room_id, 'transfer', user_id=users[1].pk)
    action(client, room_id, 'leave')
    client.force_authenticate(users[1])
    action(client, room_id, 'close')
    assert client.get(ROOT + f'rooms/{room_id}/messages/').status_code == 404


def test_files_are_private_bound_once_and_revoked(ctx):
    client, users, _ = ctx
    room_id = group(client, users)
    file = upload(client, room_id)
    client.force_authenticate(users[1])
    assert access(client, file['id']).status_code == 403
    send(client, room_id, attachments=[file['id']], expected=400)
    client.force_authenticate(users[0])
    item = send(client, room_id, attachments=[file['id']])
    send(client, room_id, key='reuse', attachments=[file['id']], expected=400)
    assert send(client, room_id, attachments=[file['id']])['id'] == item['id']
    client.force_authenticate(users[1])
    url = access(client, file['id']).data['url']
    response = APIClient().get(url)
    assert response.status_code == 200 and b''.join(response.streaming_content) == b'hello'
    assert response['Content-Disposition'].startswith('attachment;')
    assert response['Cache-Control'] == 'private, no-store'
    client.force_authenticate(users[0])
    action(client, room_id, 'remove', user_id=users[1].pk)
    assert APIClient().get(url).status_code == 403
    own_url = access(client, file['id']).data['url']
    client.post(ROOT + f"rooms/{room_id}/messages/{item['id']}/withdraw/")
    assert APIClient().get(own_url).status_code == 403
    call_command('cleanup_community_chat')
    assert not object_path(file['id']).exists()


def test_file_validation_image_preview_and_limits(ctx):
    client, users, lobby = ctx
    output = BytesIO()
    Image.new('RGB', (8, 8), color='red').save(output, format='PNG')
    image = upload(client, lobby, 'image.png', output.getvalue())
    assert image['image'] and access(client, image['id'], True).status_code == 200
    fake = upload(client, lobby, 'fake.png', b'<svg onload="alert(1)"></svg>')
    assert not fake['image'] and access(client, fake['id'], True).status_code == 400
    Attachment.objects.filter(pk=image['id']).update(size=MAX_BYTES)
    send(client, lobby, attachments=[image['id'], fake['id']], expected=400)
    send(client, lobby, attachments=[fake['id'], fake['id']], expected=400)
    with patch('app_center.community_chat.backend.media.MAX_BYTES', 3):
        result = client.post(ROOT + f'rooms/{lobby}/uploads/', {'file': SimpleUploadedFile('large', b'1234')}, format='multipart')
        assert result.status_code == 400
    send(client, lobby, attachments=[fake['id']])
    url = access(client, fake['id']).data['url']
    users[0].is_active = False
    users[0].save(update_fields=['is_active'])
    assert APIClient().get(url).status_code == 403


def test_cleanup_only_abandoned_uploads_and_expired_tickets(ctx):
    client, users, lobby = ctx
    old, fresh, sent = [upload(client, lobby) for _ in range(3)]
    send(client, lobby, attachments=[sent['id']])
    Attachment.objects.filter(pk__in=[old['id'], sent['id']]).update(created_at=timezone.now() - timedelta(days=2))
    call_command('cleanup_community_chat')
    assert not object_path(old['id']).exists()
    assert object_path(fresh['id']).exists() and object_path(sent['id']).exists()


def test_upload_permission_rechecked_after_transfer(ctx):
    client, users, _ = ctx
    room_id = group(client, users)
    client.force_authenticate(users[1])
    from ..media import room_for as real_room_for
    def removed(user, room, **kwargs):
        if kwargs.get('lock'):
            Membership.objects.filter(user=user, room_id=room).delete()
        return real_room_for(user, room, **kwargs)
    with patch('app_center.community_chat.backend.media.room_for', side_effect=removed):
        result = client.post(ROOT + f'rooms/{room_id}/uploads/', {'file': SimpleUploadedFile('test', b'file')}, format='multipart')
    assert result.status_code == 403
    assert Attachment.objects.count() == 0


def test_deployment_checks(settings, tmp_path):
    settings.CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
    settings.COMMUNITY_CHAT_WORKERS = 2
    settings.COMMUNITY_CHAT_ROOT = tmp_path / 'private'
    settings.MEDIA_ROOT = tmp_path / 'public'
    settings.COMMUNITY_CHAT_ALLOWED_ORIGINS = ['http://localhost']
    assert [error.id for error in channel_configuration(None)] == ['community_chat.E001']
    settings.COMMUNITY_CHAT_WORKERS = 1
    settings.COMMUNITY_CHAT_ROOT = settings.MEDIA_ROOT / 'chat'
    assert [error.id for error in channel_configuration(None)] == ['community_chat.E002']


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_create_one_message(settings, tmp_path):
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    user = get_user_model().objects.create_user(username='parallel-chat')
    room = Room.objects.create(kind='lobby', unique_key='lobby', name='大厅')
    def run(_):
        close_old_connections()
        try:
            return send_message(user, room.pk, {'text': 'once', 'attachments': [], 'request_key': 'same'}).pk
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(run, range(2)))
    assert ids[0] == ids[1] and Message.objects.count() == 1

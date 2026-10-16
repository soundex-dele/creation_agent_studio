from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import json
import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from modules.execution.models import Run, RunAttempt, RunLease
from app_center.song_curator import runtime
from app_center.song_curator.extensions import run_access
from .. import views, catalog
from ..domain import identity, tracks_validated
from ..models import MusicLibrary, MusicTask, MusicImage


def song(title='Hello', artist='Adele', **extra):
    return dict(title=title, artist=artist, album='', version='', **extra)


@pytest.fixture
def ctx(db, settings, tmp_path, monkeypatch):
    settings.ARTIFACT_ROOT = tmp_path
    owner = get_user_model().objects.create_user(username='music-owner')
    user = get_user_model().objects.create_user(username='music-member')
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=user, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name='Music', slug='music-test')
    app = Application.objects.create(organization=org, category=category, name='歌曲推荐官', slug='song-curator', created_by=owner, kind='custom', visibility='organization')
    client = APIClient(); client.force_authenticate(user)
    base = f'/api/v1/organizations/{org.pk}/applications/{app.pk}/song-curator'
    def start(**kw):
        return Run.objects.create(organization_id=kw['organization_id'], owner=kw['actor'], source_type='application',
            source_id=str(kw['application_id']), executor_kind='media', executor_key='song-curator', input=kw['input_data']), False
    monkeypatch.setattr(views, 'start_application_run', start)
    return SimpleNamespace(client=client, base=base, owner=owner, user=user, org=org, app=app)


def mutation(ctx, action, **values):
    revision = ctx.client.get(ctx.base + '/state').data['revision']
    return ctx.client.patch(ctx.base + '/state', {'action': action, 'revision': revision, 'requestKey': str(uuid4()), **values}, format='json')


def task(ctx, kind='conditions', **values):
    revision = ctx.client.get(ctx.base + '/state').data['revision']
    response = ctx.client.post(ctx.base + '/tasks', {'kind': kind, 'revision': revision, 'requestKey': str(uuid4()), **values}, format='json')
    assert response.status_code == 202, response.data
    return MusicTask.objects.select_related('library__owner', 'library__organization', 'run').get(pk=response.data['id'])


def execute(row):
    run = row.run
    attempt = RunAttempt.objects.create(run=run, attempt_no=1, worker_pool='media', status='running')
    RunLease.objects.create(attempt=attempt, worker_id='test', epoch=1, heartbeat_at=timezone.now(), expires_at=timezone.now()+timedelta(minutes=5))
    run.status = 'running'; run.current_attempt = attempt; run.save()
    return runtime.execute({'run_id': str(run.pk), 'organization_id': str(run.organization_id), 'attempt_id': str(attempt.pk), 'input': {'task_id': str(row.pk)}}, SimpleNamespace(cancelled=False, emit=lambda *args: None))


def upload(ctx):
    stream = BytesIO(); Image.new('RGB', (30, 20)).save(stream, format='PNG')
    response = ctx.client.post(ctx.base + '/images', {'file': SimpleUploadedFile('list.png', stream.getvalue(), content_type='image/png')}, HTTP_IDEMPOTENCY_KEY=str(uuid4()))
    assert response.status_code == 201, response.data
    return response.data['id']


def test_playlist_crud_idempotency_conflict_and_exports(ctx):
    body = {'revision': 0, 'requestKey': 'same', 'action': 'create', 'name': '收藏', 'tracks': [song(), song(), song(artist='Other'), {**song(), 'version': 'Live'}]}
    result = ctx.client.patch(ctx.base+'/state', body, format='json')
    assert result.status_code == 200, result.data
    playlist = result.data['playlists'][0]
    assert len(playlist['tracks']) == 3
    assert ctx.client.patch(ctx.base+'/state', body, format='json').data == result.data
    assert ctx.client.patch(ctx.base+'/state', {**body, 'name': 'other'}, format='json').status_code == 409
    assert ctx.client.patch(ctx.base+'/state', {**body, 'requestKey': 'new'}, format='json').status_code == 409
    assert mutation(ctx, 'rename', playlistId=playlist['id'], name='新名称').data['playlists'][0]['name'] == '新名称'
    assert mutation(ctx, 'remove', playlistId=playlist['id'], trackIds=[playlist['tracks'][0]['id']]).status_code == 200
    assert mutation(ctx, 'add', playlistId=playlist['id'], tracks=[song('=IMPORTXML(1)')]).status_code == 200
    csv = ctx.client.get(ctx.base+f"/playlists/{playlist['id']}/export?fileType=csv")
    assert "'=IMPORTXML(1)" in csv.content.decode('utf-8-sig')
    assert 'Hello' in ctx.client.get(ctx.base+f"/playlists/{playlist['id']}/export").content.decode()
    assert mutation(ctx, 'delete', playlistId=playlist['id']).data['playlists'] == []


def test_private_data_images_tasks_and_revoked_access(ctx):
    playlist = mutation(ctx, 'create', name='Private', tracks=[song()]).data['playlists'][0]
    image = upload(ctx); row = task(ctx)
    assert run_access(ctx.user, row.run)
    assert not run_access(ctx.owner, row.run)
    ctx.client.force_authenticate(ctx.owner)
    assert ctx.client.get(ctx.base+'/state').data['playlists'] == []
    for suffix in [f'/images/{image}', f'/tasks/{row.pk}', f"/playlists/{playlist['id']}/export"]:
        assert ctx.client.get(ctx.base+suffix).status_code == 404
    assert mutation(ctx, 'delete', playlistId=playlist['id']).status_code == 404
    ctx.client.force_authenticate(ctx.user)
    ctx.app.is_active = False; ctx.app.save()
    assert ctx.client.get(ctx.base+'/state').status_code == 404
    assert not run_access(ctx.user, row.run)
    assert APIClient().get(ctx.base+'/state').status_code in (401, 403)


def test_image_import_is_reviewable_atomic_and_deletion_cleans(ctx, monkeypatch, django_capture_on_commit_callbacks):
    image = upload(ctx)
    row = task(ctx, 'import', imageIds=[image])
    monkeypatch.setattr(runtime, 'generate_json', Mock(return_value={'tracks': [song(artist='', sourceImageId=image, note='歌手模糊'), song(artist='', sourceImageId=image)]}))
    execute(row); row.refresh_from_db()
    assert row.status == 'succeeded', row.error
    assert row.result['tracks'][0]['artist'] == ''
    assert len(row.result['tracks']) == 1
    assert len(runtime.generate_json.call_args.kwargs['image_paths']) == 1
    assert ctx.client.get(ctx.base+'/state').data['playlists'] == []
    response = mutation(ctx, 'confirm', taskId=str(row.pk), name='导入', tracks=[song('Corrected')], requestKey='confirm-once')
    assert response.status_code == 200, response.data
    assert response.data['playlists'][0]['tracks'][0]['title'] == 'Corrected'
    assert mutation(ctx, 'confirm', taskId=str(row.pk), name='again', tracks=[song()]).status_code == 409
    with django_capture_on_commit_callbacks(execute=True):
        assert ctx.client.delete(ctx.base+f'/tasks/{row.pk}').status_code == 204
    assert not MusicImage.objects.filter(pk=image).exists()
    assert len(ctx.client.get(ctx.base+'/state').data['playlists']) == 1


def test_task_replay_payload_and_invalid_images(ctx):
    body = {'kind': 'conditions', 'revision': 0, 'requestKey': 'task-key'}
    first = ctx.client.post(ctx.base+'/tasks', body, format='json')
    assert first.status_code == 202
    assert ctx.client.post(ctx.base+'/tasks', body, format='json').data['id'] == first.data['id']
    assert ctx.client.post(ctx.base+'/tasks', {**body, 'kind': 'similar', 'playlistId': str(uuid4())}, format='json').status_code == 409
    invalid = ctx.client.post(ctx.base+'/images', {'file': SimpleUploadedFile('bad.png', b'bad')}, HTTP_IDEMPOTENCY_KEY='bad')
    assert invalid.status_code == 400
    for ids in [[], [str(uuid4())]*6, [str(uuid4())]]:
        assert ctx.client.post(ctx.base+'/tasks', {**body, 'requestKey': str(uuid4()), 'kind': 'import', 'imageIds': ids}, format='json').status_code == 400


def test_recommendation_filters_feedback_deduplication_and_no_playlist_mutation(ctx, monkeypatch):
    seeds = mutation(ctx, 'create', name='Seeds', tracks=[song('Seed')]).data['playlists'][0]
    mutation(ctx, 'feedback', tracks=[song('Blocked')], feedback='dislike')
    mutation(ctx, 'feedback', tracks=[song('Heard')], feedback='heard')
    mutation(ctx, 'feedback', tracks=[song('Liked')], feedback='like')
    row = task(ctx, 'similar', playlistId=seeds['id'], filters={'genre': '爵士', 'scene': '雨天', 'language': 'zh'})
    before = deepcopy(ctx.client.get(ctx.base+'/state').data)
    monkeypatch.setattr(runtime, 'generate_json', Mock(return_value={'tracks': [song(title, reason='温暖的人声') for title in ['Seed', 'Blocked', 'Heard', 'New', 'New']]}))
    monkeypatch.setattr(runtime, 'verify', lambda *args: {'status': 'unavailable', 'source': 'iTunes', 'checkedAt': timezone.now().isoformat()})
    execute(row); row.refresh_from_db()
    assert [t['title'] for t in row.result['tracks']] == ['New']
    assert row.result['tracks'][0]['verification']['status'] == 'unavailable'
    prompt = json.loads(runtime.generate_json.call_args.kwargs['content'])
    assert prompt['filters']['genre'] == '爵士' and prompt['likes'][0]['title'] == 'Liked'
    assert ctx.client.get(ctx.base+'/state').data == before
    assert mutation(ctx, 'feedback', tracks=[song('Heard')], feedback='none').status_code == 200


def test_long_playlist_all_batches_and_recent_exclusion(ctx, monkeypatch):
    playlist = mutation(ctx, 'create', name='Long', tracks=[song(f'Song {i}') for i in range(121)]).data['playlists'][0]
    row = task(ctx, 'similar', playlistId=playlist['id'])
    calls = []
    def model(**kw):
        data = json.loads(kw['content']); calls.append(data)
        return {'profile': '华语流行'} if 'tracks' in data else {'tracks': []}
    monkeypatch.setattr(runtime, 'generate_json', model)
    execute(row); row.refresh_from_db()
    assert [len(c['tracks']) for c in calls if 'tracks' in c] == [50, 50, 21]
    assert row.result['processedSeeds'] == 121
    assert len(calls[-1]['seedProfiles']) == 3


@pytest.mark.parametrize('value', [{}, {'tracks': 'bad'}, {'tracks': [song(reason='')]}, {'tracks': [song(artist='', reason='reason')]}])
def test_invalid_model_outputs_fail_without_publishing(ctx, monkeypatch, value):
    row = task(ctx)
    monkeypatch.setattr(runtime, 'generate_json', lambda **kw: value)
    with pytest.raises(RuntimeError): execute(row)
    row.refresh_from_db(); assert row.status == 'failed' and row.result == {}


def test_cancelled_late_result_and_expired_lease(ctx, monkeypatch):
    row = task(ctx)
    def late(**kw):
        MusicTask.objects.filter(pk=row.pk).update(cancel_requested=True, status='cancelled')
        return {'tracks': []}
    monkeypatch.setattr(runtime, 'generate_json', late)
    with pytest.raises(InterruptedError): execute(row)
    row.refresh_from_db(); assert row.result == {} and row.status == 'cancelled'
    row2 = task(ctx)
    def expired(**kw):
        RunLease.objects.filter(attempt__run=row2.run).update(expires_at=timezone.now()-timedelta(seconds=1))
        return {'tracks': []}
    monkeypatch.setattr(runtime, 'generate_json', expired)
    with pytest.raises(InterruptedError): execute(row2)
    row2.refresh_from_db(); assert row2.result == {}


def test_real_install_and_submission(ctx, monkeypatch):
    monkeypatch.undo()
    call_command('sync_app_center', package_id='song-curator', organization_id=str(ctx.org.pk))
    call_command('sync_app_center', package_id='song-curator', organization_id=str(ctx.org.pk))
    ctx.app.refresh_from_db()
    assert ctx.app.deployments.count() == 1
    row = task(ctx)
    assert row.run.executor_key == 'song-curator' and row.run.owner_id == ctx.user.pk
    assert ctx.client.post(ctx.base+f'/tasks/{row.pk}/cancel').status_code == 200
    row.refresh_from_db(); assert row.cancel_requested


def test_catalog_exact_version_ambiguity_and_outage(monkeypatch):
    row = {'trackName': 'Hello', 'artistName': 'Adele', 'trackId': 1, 'trackViewUrl': 'https://music.apple.com/us/album/hello/1', 'collectionName': '25'}
    monkeypatch.setattr(catalog, 'search', lambda *args: [row, {**row, 'trackName': 'Hello (Live)', 'trackId': 2}])
    assert catalog.verify(song())['catalogId'] == '1'
    assert catalog.verify({**song(), 'version': 'Live'})['catalogId'] == '2'
    monkeypatch.setattr(catalog, 'search', lambda *args: [row, {**row, 'trackId': 3}])
    assert catalog.verify(song())['status'] == 'ambiguous'
    assert catalog.verify(song(artist='Someone Else'))['status'] == 'not_found'
    assert catalog.verify(song(artist=''))['status'] == 'ambiguous'
    monkeypatch.setattr(catalog, 'search', Mock(side_effect=RuntimeError('503')))
    assert catalog.verify(song())['status'] == 'unavailable'


@pytest.mark.django_db
def test_catalog_cache_fixed_endpoint_and_cancel(monkeypatch):
    from django.core.cache import cache
    cache.clear()
    response = Mock(status_code=200)
    response.iter_content.return_value = [json.dumps({'results': []}).encode()]
    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    get = Mock(return_value=response); monkeypatch.setattr(catalog.requests, 'get', get)
    assert catalog.search('Hello Adele', 'US') == []
    assert catalog.search('Hello Adele', 'US') == []
    assert get.call_count == 1 and get.call_args.args[0] == catalog.ENDPOINT
    assert get.call_args.kwargs['allow_redirects'] is False
    with pytest.raises(InterruptedError): catalog.search('Other', 'US', lambda: True)


def test_model_quota_failure_does_not_modify_library(ctx, monkeypatch):
    from rest_framework.exceptions import Throttled
    row = task(ctx)
    monkeypatch.setattr(runtime, 'generate_json', Mock(side_effect=Throttled(detail='Quota')))
    with pytest.raises(RuntimeError): execute(row)
    row.refresh_from_db(); assert row.status == 'failed' and row.result == {}
    assert not row.library.playlists.exists()


@pytest.mark.parametrize('rows', [[], [{'title': '晴天', 'artist': '', 'album': '', 'version': '', 'sourceImageId': 'invalid'}]])
def test_empty_and_invalid_source_recognition(ctx, monkeypatch, rows):
    image = upload(ctx); row = task(ctx, 'import', imageIds=[image])
    monkeypatch.setattr(runtime, 'generate_json', lambda **kw: {'tracks': rows})
    if rows:
        with pytest.raises(RuntimeError): execute(row)
    else:
        execute(row)
        row.refresh_from_db(); assert row.result['tracks'] == [] and '未发现' in row.result['notice']
    assert not row.library.playlists.exists()


def test_cross_organization_task_and_image_inaccessible(ctx):
    image = upload(ctx); row = task(ctx)
    other_base = ctx.base.replace(str(ctx.org.pk), str(ctx.user.owned_organizations.get().pk))
    assert ctx.client.get(other_base + f'/images/{image}').status_code == 404
    assert ctx.client.get(other_base + f'/tasks/{row.pk}').status_code == 404


def test_recent_tracks_excluded_and_payload_snapshots_immutable(ctx, monkeypatch):
    first = task(ctx)
    first.status = 'succeeded'; first.result = {'tracks': [song('Recent')]}; first.save()
    second = task(ctx)
    mutation(ctx, 'feedback', tracks=[song('Changed later')], feedback='dislike')
    assert second.snapshot['feedback'] == []
    monkeypatch.setattr(runtime, 'generate_json', lambda **kw: {'tracks': [song('Recent', reason='similar')]})
    execute(second); second.refresh_from_db()
    assert second.result['tracks'] == []


def test_cleanup_expired_uploads_and_image_upload_replay(ctx):
    image_id = upload(ctx)
    image = MusicImage.objects.get(pk=image_id)
    from modules.platform_api.artifacts import get_artifact_storage
    with get_artifact_storage().open(image.object_key) as handle:
        content = handle.read()
    response = ctx.client.post(ctx.base+'/images', {'file': SimpleUploadedFile('retry.png', content)}, HTTP_IDEMPOTENCY_KEY=image.request_key)
    assert response.status_code == 200 and response.data['id'] == image_id
    MusicImage.objects.filter(pk=image_id).update(created_at=timezone.now()-timedelta(days=2))
    call_command('cleanup_song_images')
    assert not MusicImage.objects.filter(pk=image_id).exists()


def test_version_deduplication_keeps_studio_and_live_separate():
    rows = tracks_validated([song(), song('Hello (Live)'), {**song(), 'version': 'Live'}])
    assert len(rows) == 2

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.user_directories import user_directory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def private_root(tmp_path, settings):
    settings.AGENT_WORKSPACE_ROOT = tmp_path / 'workspaces'
    settings.APPLICATION_RUNTIME_ALLOW_ALL_PATHS = True


def _client(role='member', **extra):
    user = get_user_model().objects.create_user(username=f'runtime-{role}', role=role, **extra)
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def test_new_users_have_distinct_private_directories():
    first, client = _client()
    second, _ = _client('auditor')
    assert user_directory(first).is_dir()
    assert user_directory(first) != user_directory(second)
    response = client.get('/api/v1/apps/runtime-files/list/')
    assert [item['path'] for item in response.data['roots']] == [str(user_directory(first))]
    response = client.get('/api/v1/apps/runtime-files/list/', {'path': str(user_directory(first))})
    assert response.data['parent'] == ''


def test_scan_runtime_folder_lists_only_own_videos(tmp_path):
    user, client = _client()
    root = user_directory(user)
    (root / 'a.mp4').touch()
    (root / 'b.txt').write_text('x')
    outside = tmp_path / 'secret.mp4'
    outside.touch()
    (root / 'escape.mp4').symlink_to(outside)
    (root / 'escape-dir').symlink_to(tmp_path, target_is_directory=True)
    response = client.post('/api/v1/apps/runtime-files/scan/', {'path': str(root)}, format='json')
    assert response.status_code == 200
    assert [item['name'] for item in response.data['videos']] == ['a.mp4']
    response = client.get('/api/v1/apps/runtime-files/list/', {'path': str(root)})
    assert response.data['dirs'] == []


@pytest.mark.parametrize('role,extra', [('member', {}), ('auditor', {}), ('member', {'is_staff': True})])
def test_non_admin_cannot_escape_even_when_allow_all_is_enabled(tmp_path, settings, role, extra):
    user, client = _client(role, **extra)
    other = get_user_model().objects.create_user(username='other')
    root = user_directory(user)
    settings.APPLICATION_RUNTIME_ALLOWED_ROOTS = [str(tmp_path)]
    (root / 'escape').symlink_to(user_directory(other), target_is_directory=True)
    for path in (tmp_path, user_directory(other), root / '..', root / 'escape'):
        assert client.get('/api/v1/apps/runtime-files/list/', {'path': str(path)}).status_code == 403
        assert client.post('/api/v1/apps/runtime-files/scan/', {'path': str(path)}, format='json').status_code == 403
        assert client.post('/api/v1/conversations/', {'working_directory': str(path)}, format='json').status_code == 400
        assert client.post('/api/v1/projects/?scope=cowork', {'scope': 'cowork', 'working_directory': str(path)}, format='json').status_code == 400


@pytest.mark.parametrize('role,extra', [('admin', {}), ('member', {'is_superuser': True})])
def test_admin_can_access_all_paths(tmp_path, role, extra):
    _, client = _client(role, **extra)
    response = client.get('/api/v1/apps/runtime-files/list/', {'path': str(tmp_path)})
    assert response.status_code == 200
    assert response.data['path'] == str(tmp_path.resolve())


def test_configured_restrictions_still_apply_to_admin(tmp_path, settings):
    settings.APPLICATION_RUNTIME_ALLOW_ALL_PATHS = False
    settings.APPLICATION_RUNTIME_ALLOWED_ROOTS = []
    _, client = _client('admin')
    assert client.get('/api/v1/apps/runtime-files/list/', {'path': str(tmp_path)}).status_code == 403


def test_anonymous_is_denied():
    assert APIClient().get('/api/v1/apps/runtime-files/list/').status_code in (401, 403)


def test_replaced_user_root_symlink_is_rejected(tmp_path):
    user, _ = _client()
    root = user_directory(user)
    root.rmdir()
    root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PermissionError):
        user_directory(user)


def test_worker_payload_uses_current_owner_role(settings):
    from types import SimpleNamespace
    from modules.execution.infrastructure.coordinator import ExecutionCoordinator

    user, _ = _client()
    run = SimpleNamespace(id='run', organization_id='org', executor_key='test',
                          definition_snapshot={}, input={'allow_all_paths': True}, created_by=user)
    claimed = SimpleNamespace(run=run, attempt=SimpleNamespace(id='attempt', checkpoint_artifact=None),
                              resume_command=None)
    coordinator = ExecutionCoordinator(worker_id='test', worker_pool='default')
    payload = coordinator._payload(claimed)
    assert payload['allowed_roots'] == [str(user_directory(user))]
    assert payload['allow_all_paths'] is False
    user.role = 'admin'
    assert coordinator._payload(claimed)['allow_all_paths'] is True


def test_same_organization_has_separate_workspaces():
    from apps.projects.services.workspace_paths import system_working_directory
    from apps.enterprise.models import Membership

    first, _ = _client()
    second, _ = _client('auditor')
    organization = first.owned_organizations.get()
    Membership.objects.create(organization=organization, user=second)
    assert system_working_directory(first, organization) != system_working_directory(second, organization)


def test_legacy_saved_directory_cannot_bypass_policy(tmp_path):
    from apps.conversations.models import Conversation
    from apps.projects.models import Project
    from apps.projects.services.workspace_paths import application_working_directory, conversation_working_directory
    from rest_framework.exceptions import PermissionDenied

    user, _ = _client()
    organization = user.owned_organizations.get()
    conversation = Conversation.objects.create(user=user, organization=organization, working_directory=str(tmp_path))
    with pytest.raises(PermissionDenied):
        conversation_working_directory(conversation)
    other = get_user_model().objects.create_user(username='other')
    project = Project.objects.create(user=user, organization=organization, working_directory=str(user_directory(other)))
    with pytest.raises(PermissionDenied):
        application_working_directory(project)


def test_backfill_is_idempotent():
    from django.core.management import call_command

    user, _ = _client()
    root = user_directory(user)
    root.rmdir()
    call_command('provision_user_directories', verbosity=0)
    (root / 'keep.txt').write_text('keep')
    call_command('provision_user_directories', verbosity=0)
    assert (root / 'keep.txt').read_text() == 'keep'


def test_creation_master_uses_user_policy_despite_legacy_global_flag(tmp_path, settings):
    from apps.applications.models import Application, ApplicationCategory
    from app_center.creation_master.backend.views import CreationMasterDirectoryView, CreationMasterScanView
    from rest_framework.test import APIRequestFactory, force_authenticate

    settings.CREATION_MASTER_ALLOW_ALL_PATHS = True
    user, _ = _client()
    organization = user.owned_organizations.get()
    category = ApplicationCategory.objects.create(name='Test', slug='path-test')
    application = Application.objects.create(name='Creation Master', slug='creation-master',
        category=category, organization=organization, created_by=user)
    factory = APIRequestFactory()
    params = {'organization_id': organization.pk, 'application_id': application.pk}
    for view, request in (
        (CreationMasterDirectoryView, factory.get('/', {'path': str(tmp_path)})),
        (CreationMasterScanView, factory.post('/', {'folder': str(tmp_path)}, format='json')),
    ):
        force_authenticate(request, user=user)
        assert view.as_view()(request, **params).status_code == 403
    request = factory.get('/', {'path': str(user_directory(user))})
    force_authenticate(request, user=user)
    response = CreationMasterDirectoryView.as_view()(request, **params)
    assert response.status_code == 200
    assert response.data['parent'] == ''


def test_creation_master_runtime_cannot_use_legacy_global_flag(tmp_path, settings):
    from app_center.creation_master.backend.runtime import execute_creation_master

    settings.CREATION_MASTER_ALLOW_ALL_PATHS = True
    user, _ = _client()
    with pytest.raises(PermissionError):
        execute_creation_master({'allowed_roots': [str(user_directory(user))],
                                 'input': {'operation': 'rename', 'folder': str(tmp_path)}}, None)


def test_agent_runtime_rejects_legacy_full_control_payload():
    from apps.agents.execution import execute_agent_completion

    with pytest.raises(PermissionError):
        execute_agent_completion({'input': {'permission_mode': 'allow_all'},
                                  'allow_all_paths': False}, None)

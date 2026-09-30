import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.conf import settings
from rest_framework.test import APIClient

from apps.conversations.models import Conversation, Message
from apps.enterprise.models import Organization, Membership
from apps.projects.models import Project
from apps.projects.services.workspace_paths import conversation_working_directory
from apps.users.models import User
from modules.execution.models import Run


@override_settings(SINGLE_TENANT_MODE=False)
class CoworkTest(TestCase):
    def test_cowork_package_is_discoverable(self):
        from apps.applications.app_center.discovery import discover_packages
        packages, _ = discover_packages(settings.APP_CENTER_ROOT)
        package = next(item for item in packages if item.manifest.metadata.id == 'cowork')
        self.assertEqual(package.manifest.spec.definition['renderer_key'], 'cowork')

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'explicit'
        self.folder.mkdir()
        self.settings_override = override_settings(
            AGENT_WORKSPACE_ROOT=str(Path(self.temp.name) / 'managed'),
            APPLICATION_RUNTIME_ALLOW_ALL_PATHS=True)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = User.objects.create_user('cowork-owner')
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(self.organization.id))

    def project(self, **extra):
        response = self.client.post('/api/v1/projects/?scope=cowork', {
            'scope': 'cowork', 'working_directory': str(self.folder), **extra,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def conversation(self, **extra):
        response = self.client.post('/api/v1/conversations/?scope=cowork', {
            'scope': 'cowork', 'title': 'CoWork task', **extra,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def workspace(self, conversation, payload):
        return self.client.post(f"/api/v1/conversations/{conversation['id']}/workspace/?scope=cowork", payload, format='json')

    def test_default_directory_is_not_a_project(self):
        conversation = self.conversation()
        self.assertIsNone(conversation['project'])
        self.assertTrue(Path(conversation['working_directory']).is_dir())
        self.assertFalse(Project.objects.filter(scope='cowork').exists())
        recent = self.client.get('/api/v1/conversations/?scope=cowork&page=1')
        self.assertEqual([row['id'] for row in recent.data['results']], [conversation['id']])
        self.assertEqual(self.client.get('/api/v1/conversations/').data, [])

    def test_binding_creates_project_and_reuses_normalized_directory(self):
        first = self.conversation(working_directory=str(self.folder))
        second = self.project(working_directory=str(self.folder / '..' / 'explicit'))
        third = self.conversation(project_id=second['id'])
        self.assertEqual(first['project'], second['id'])
        self.assertEqual(third['working_directory'], str(self.folder.resolve()))
        self.assertEqual(second['directory_source'], 'explicit')
        self.assertEqual(second['title'], 'explicit')
        self.assertEqual(Project.objects.filter(scope='cowork').count(), 1)
        if os.name == 'nt':
            self.assertEqual(self.project(working_directory=str(self.folder).upper())['id'], second['id'])

    def test_project_chats_also_appear_in_recents(self):
        project = self.project()
        one = self.conversation(project_id=project['id'])
        two = self.conversation()
        recent = self.client.get('/api/v1/conversations/?scope=cowork&page=1').data['results']
        self.assertEqual([row['id'] for row in recent], [two['id'], one['id']])
        grouped = self.client.get('/api/v1/conversations/', {'scope': 'cowork', 'project_id': project['id']}).data
        self.assertEqual([row['id'] for row in grouped], [one['id']])
        default = self.client.get('/api/v1/projects/').data
        self.assertEqual(default['results'] if isinstance(default, dict) else default, [])

    def test_new_project_requires_an_explicit_existing_folder(self):
        for payload in ({'scope': 'cowork', 'title': 'No folder'},
                        {'scope': 'cowork', 'working_directory': str(self.folder / 'missing')}):
            response = self.client.post('/api/v1/projects/', payload, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Project.objects.filter(scope='cowork').exists())

    def test_switch_and_unbind_preserve_files_and_reset_execution_thread(self):
        conversation = self.conversation()
        Conversation.objects.filter(pk=conversation['id']).update(agent_thread_provider='codex', agent_thread_id='old')
        response = self.workspace(conversation, {'working_directory': str(self.folder)})
        self.assertEqual(response.status_code, 200, response.data)
        project_id = response.data['project']
        self.assertIsNotNone(project_id)
        marker = self.folder / 'keep.txt'
        marker.write_text('keep', encoding='utf-8')
        self.assertEqual(Conversation.objects.get(pk=conversation['id']).agent_thread_id, '')
        response = self.workspace(conversation, {'project_id': None, 'working_directory': ''})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data['project'])
        self.assertNotEqual(response.data['working_directory'], str(self.folder))
        self.assertTrue(marker.is_file())
        self.assertTrue(Project.objects.filter(pk=project_id).exists())

    def test_failed_binding_leaves_original_workspace(self):
        conversation = self.conversation(working_directory=str(self.folder))
        response = self.workspace(conversation, {'working_directory': str(self.folder / 'missing')})
        self.assertEqual(response.status_code, 400)
        saved = Conversation.objects.get(pk=conversation['id'])
        self.assertEqual(saved.project_id, conversation['project'])
        self.assertEqual(saved.working_directory, conversation['working_directory'])

    def test_first_user_message_locks_workspace_and_rejects_every_switch(self):
        project = self.project()
        for initial in ({}, {'project_id': project['id']}):
            with self.subTest(initial=initial):
                conversation = self.conversation(**initial)
                endpoint = f"/api/v1/conversations/{conversation['id']}/?scope=cowork"
                self.assertFalse(self.client.get(endpoint).data['workspace_locked'])
                Message.objects.create(conversation_id=conversation['id'], role='user', content='Start work')
                self.assertTrue(self.client.get(endpoint).data['workspace_locked'])
                another = Path(self.temp.name) / 'another'
                another.mkdir(exist_ok=True)
                for payload in ({'project_id': project['id']},
                                {'project_id': None, 'working_directory': ''},
                                {'working_directory': str(another)}):
                    response = self.workspace(conversation, payload)
                    self.assertEqual(response.status_code, 409, response.data)
                    self.assertIn('新建对话', response.data['detail'])
                saved = Conversation.objects.get(pk=conversation['id'])
                self.assertEqual(saved.project_id, conversation['project'])
                self.assertEqual(saved.working_directory, conversation['working_directory'])
                self.assertEqual(Project.objects.filter(scope='cowork').count(), 1)

    def test_system_message_does_not_lock_an_unsent_cowork_conversation(self):
        conversation = self.conversation()
        Message.objects.create(conversation_id=conversation['id'], role='system', content='Instructions')
        response = self.workspace(conversation, {'working_directory': str(self.folder)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['workspace_locked'])

    def test_default_conversation_is_not_locked_by_a_user_message(self):
        conversation = Conversation.objects.create(user=self.user, organization=self.organization)
        Message.objects.create(conversation=conversation, role='user', content='Hello')
        self.assertFalse(conversation.workspace_locked)

    def test_missing_bound_directory_does_not_fall_back_or_recreate(self):
        conversation = self.conversation(working_directory=str(self.folder))
        self.folder.rmdir()
        response = self.client.get(f"/api/v1/conversations/{conversation['id']}/workspace-files/?scope=cowork")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(self.folder.exists())

    def test_bound_files_are_available_through_the_conversation(self):
        conversation = self.conversation(working_directory=str(self.folder))
        (self.folder / 'result.md').write_text('# CoWork result', encoding='utf-8')
        endpoint = f"/api/v1/conversations/{conversation['id']}/workspace-files/"
        listing = self.client.get(endpoint, {'scope': 'cowork'})
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data['working_directory'], str(self.folder.resolve()))
        preview = self.client.get(endpoint, {'scope': 'cowork', 'path': 'result.md'})
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['content'], '# CoWork result')

    def test_remove_project_deletes_chats_but_keeps_folder_and_files(self):
        conversation = self.conversation(working_directory=str(self.folder))
        other = self.conversation()
        marker = self.folder / 'valuable.txt'
        marker.write_text('keep me', encoding='utf-8')
        response = self.client.delete(f"/api/v1/projects/{conversation['project']}/?scope=cowork")
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(Conversation.objects.filter(pk=conversation['id']).exists())
        self.assertFalse(Project.objects.filter(pk=conversation['project']).exists())
        self.assertTrue(Conversation.objects.filter(pk=other['id']).exists())
        self.assertEqual(marker.read_text(encoding='utf-8'), 'keep me')
        recent = self.client.get('/api/v1/conversations/?scope=cowork').data
        self.assertEqual([row['id'] for row in recent], [other['id']])

    def test_active_run_blocks_switch_and_project_removal(self):
        conversation = self.conversation(working_directory=str(self.folder))
        Run.objects.create(organization=self.organization, owner=self.user,
            executor_kind='agent', executor_key='general', source_type='conversation',
            source_id=str(conversation['id']), status='running')
        another = Path(self.temp.name) / 'another'
        another.mkdir()
        response = self.workspace(conversation, {'working_directory': str(another)})
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(Project.objects.filter(scope='cowork').count(), 1)
        response = self.client.delete(f"/api/v1/projects/{conversation['project']}/?scope=cowork")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(Conversation.objects.filter(pk=conversation['id']).exists())

    def test_scope_and_user_boundaries(self):
        project = self.project()
        cowork = self.conversation(project_id=project['id'])
        self.assertEqual(self.client.get(f"/api/v1/conversations/{cowork['id']}/").status_code, 404)
        normal = self.client.post('/api/v1/conversations/', {'title': 'Normal'}, format='json')
        self.assertEqual(normal.status_code, 201, normal.data)
        response = self.client.get(f"/api/v1/conversations/{normal.data['id']}/?scope=cowork")
        self.assertEqual(response.status_code, 404)
        response = self.client.post('/api/v1/conversations/', {'project_id': project['id']}, format='json')
        self.assertEqual(response.status_code, 404)
        other = User.objects.create_user('cowork-other')
        Membership.objects.get_or_create(organization=self.organization, user=other)
        self.client.force_authenticate(other)
        response = self.client.patch(f"/api/v1/projects/{project['id']}/?scope=cowork", {'title': 'Stolen'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(self.project()['id'], project['id'])

    def test_organization_boundary(self):
        project = self.project()
        other_org = Organization.objects.create(name='Other organization', slug='cowork-other-org', owner=self.user)
        Membership.objects.get_or_create(organization=other_org, user=self.user, defaults={'role': 'owner'})
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(other_org.id))
        response = self.client.delete(f"/api/v1/projects/{project['id']}/?scope=cowork")
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(self.project()['id'], project['id'])

    def test_rename_does_not_change_bound_directory(self):
        project = self.project()
        response = self.client.patch(f"/api/v1/projects/{project['id']}/?scope=cowork", {'title': 'New name'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['title'], 'New name')
        self.assertEqual(response.data['working_directory'], project['working_directory'])

    def test_directory_policy_and_pagination(self):
        with override_settings(APPLICATION_RUNTIME_ALLOW_ALL_PATHS=False, APPLICATION_RUNTIME_ALLOWED_ROOTS=[]):
            response = self.client.post('/api/v1/projects/', {'scope': 'cowork', 'working_directory': str(self.folder)}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        for number in range(21):
            Conversation.objects.create(user=self.user, organization=self.organization, scope='cowork', title=str(number))
        first = self.client.get('/api/v1/conversations/?scope=cowork&page=1').data
        second = self.client.get('/api/v1/conversations/?scope=cowork&page=2').data
        self.assertEqual(len(first['results']), 20)
        self.assertIsNotNone(first['next'])
        self.assertEqual(len(second['results']), 1)

    def test_default_project_allocation_is_unchanged(self):
        normal = self.client.post('/api/v1/projects/', {'title': 'Legacy'}, format='json')
        self.assertEqual(normal.status_code, 201, normal.data)
        self.assertEqual(normal.data['scope'], 'default')
        self.assertEqual(normal.data['directory_source'], 'managed')
        conversation = Conversation.objects.create(user=self.user, organization=self.organization, project_id=normal.data['id'])
        self.assertEqual(conversation_working_directory(conversation), normal.data['working_directory'])

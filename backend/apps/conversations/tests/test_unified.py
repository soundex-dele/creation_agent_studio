from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.conversations.models import Conversation, Message
from apps.enterprise.models import Membership, Organization
from apps.projects.models import Project
from apps.users.models import User
from modules.execution.models import Run


@override_settings(SINGLE_TENANT_MODE=False)
class UnifiedConversationTest(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = override_settings(AGENT_WORKSPACE_ROOT=self.temp.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user('unified-owner')
        self.organization = self.user.owned_organizations.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(self.organization.id))

    def conversation(self, scope='default', **kwargs):
        return Conversation.objects.create(
            user=self.user, organization=self.organization, scope=scope, **kwargs)

    def endpoint(self, conversation, action=''):
        return f'/api/v1/conversations/{conversation.id}/{action}?scope=unified'

    def test_history_is_union_with_stable_pagination_and_project_filter(self):
        project = Project.objects.create(user=self.user, organization=self.organization, title='Workflow')
        excluded = self.conversation(project=project)
        expected = [self.conversation('cowork' if index % 2 else 'default', title=f'Chat {index}') for index in range(25)]
        tied_time = timezone.now()
        Conversation.objects.filter(pk__in=[item.pk for item in expected]).update(updated_at=tied_time)
        first = self.client.get('/api/v1/conversations/?scope=unified&page=1').data
        second = self.client.get('/api/v1/conversations/?scope=unified&page=2').data
        self.assertEqual(first['count'], 25)
        self.assertEqual([row['id'] for row in first['results'] + second['results']], [item.pk for item in reversed(expected)])
        filtered = self.client.get('/api/v1/conversations/', {'scope': 'unified', 'project_id': project.pk}).data
        self.assertEqual([row['id'] for row in filtered], [excluded.pk])
        self.assertEqual(len(self.client.get('/api/v1/conversations/').data), 13)
        self.assertEqual(len(self.client.get('/api/v1/conversations/?scope=cowork').data), 12)

    def test_cowork_project_conversations_are_in_unified_recents(self):
        from core.user_directories import user_directory
        folder = user_directory(self.user) / 'project'
        folder.mkdir()
        created = self.client.post('/api/v1/conversations/?scope=unified', {
            'scope': 'cowork', 'working_directory': str(folder),
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertIsNotNone(created.data['project'])
        response = self.client.get('/api/v1/conversations/?scope=unified&page=1')
        self.assertEqual([row['id'] for row in response.data['results']], [created.data['id']])
        self.assertEqual(created.data['scope'], 'cowork')
        self.assertEqual(self.client.get('/api/v1/conversations/').data, [])
        self.assertEqual(self.client.get('/api/v1/projects/?scope=unified').status_code, 400)
        invalid = self.client.post('/api/v1/conversations/', {'scope': 'unified'}, format='json')
        self.assertEqual(invalid.status_code, 400)

    def test_retrieve_and_continue_preserve_scope_directory_messages_and_thread(self):
        for scope in ('default', 'cowork'):
            conversation = self.conversation(scope, working_directory=str(Path(self.temp.name) / scope),
                agent_thread_provider='codex', agent_thread_id='existing-thread')
            message = Message.objects.create(conversation=conversation, role='user', content='Original')
            response = self.client.get(self.endpoint(conversation))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(str(response.data['messages'][0]['id']), str(message.pk))
            self.assertEqual(response.data['working_directory'], conversation.working_directory)
            self.assertEqual(response.data['workspace_locked'], scope == 'cowork')
            run = Run.objects.create(organization=self.organization, owner=self.user,
                executor_kind='agent', executor_key='general', source_type='conversation',
                source_id=str(conversation.id), status='succeeded')
            with patch('apps.conversations.views.create_conversation_run', return_value=(run, False)) as create_run:
                response = self.client.post(self.endpoint(conversation, 'send_message/'),
                    {'content': 'Continue'}, format='json', HTTP_IDEMPOTENCY_KEY=f'continue-{scope}')
            self.assertEqual(response.status_code, 202, response.data)
            self.assertEqual(create_run.call_args.args[1].id, conversation.id)
            conversation.refresh_from_db()
            self.assertEqual(conversation.scope, scope)
            self.assertEqual(conversation.agent_thread_id, 'existing-thread')

    def test_user_and_organization_boundaries_apply_to_all_unified_actions(self):
        conversation = self.conversation('cowork')
        other = User.objects.create_user('unified-other')
        Membership.objects.get_or_create(organization=self.organization, user=other)
        self.client.force_authenticate(other)
        for action in ('', 'workspace-files/'):
            self.assertEqual(self.client.get(self.endpoint(conversation, action)).status_code, 404)
        for action in ('clear/', 'delete_conversation/'):
            self.assertEqual(self.client.delete(self.endpoint(conversation, action)).status_code, 404)
        for action in ('workspace/', 'send_message/'):
            self.assertEqual(self.client.post(self.endpoint(conversation, action), {}, format='json').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/conversations/?scope=unified').data, [])
        other_org = Organization.objects.create(name='Other', slug='unified-other-org', owner=self.user)
        Membership.objects.get_or_create(organization=other_org, user=self.user, defaults={'role': 'owner'})
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(other_org.id))
        self.assertEqual(self.client.get(self.endpoint(conversation)).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/conversations/?scope=unified').data, [])

    def test_workspace_uses_record_rules_and_resets_thread_only_on_change(self):
        from core.user_directories import user_directory
        directory = user_directory(self.user) / 'selected'
        directory.mkdir()
        for scope in ('default', 'cowork'):
            conversation = self.conversation(scope, agent_thread_provider='codex', agent_thread_id='thread')
            Message.objects.create(conversation=conversation, role='user', content='Sent')
            response = self.client.post(self.endpoint(conversation, 'workspace/'), {
                'working_directory': str(directory),
            }, format='json')
            self.assertEqual(response.status_code, 200 if scope == 'default' else 409, response.data)
            conversation.refresh_from_db()
            self.assertEqual(conversation.agent_thread_id, '' if scope == 'default' else 'thread')

    def test_clear_stays_empty_after_refresh_and_retains_files_and_run_history(self):
        from modules.execution.application.projections import project_terminal_run
        for scope in ('default', 'cowork'):
            conversation = self.conversation(scope)
            directory = Path(self.temp.name) / scope
            directory.mkdir()
            marker = directory / 'keep.txt'
            marker.write_text('keep')
            conversation.working_directory = str(directory)
            conversation.save()
            run = Run.objects.create(organization=self.organization, owner=self.user,
                executor_kind='agent', executor_key='general', source_type='conversation',
                source_id=str(conversation.id), status='succeeded', output_summary={'result': 'Old output'})
            Message.objects.create(conversation=conversation, role='user', content='Sent', run=run)
            response = self.client.delete(self.endpoint(conversation, 'clear/'))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIsNone(project_terminal_run(run.id, run.output_summary))
            response = self.client.get(self.endpoint(conversation))
            self.assertEqual(response.data['messages'], [])
            self.assertIsNone(response.data['latest_run'])
            self.assertEqual(response.data['workspace_locked'], scope == 'cowork')
            self.assertTrue(Run.objects.filter(pk=run.pk).exists())
            self.assertEqual(marker.read_text(), 'keep')
            new_run = Run.objects.create(organization=self.organization, owner=self.user,
                executor_kind='agent', executor_key='general', source_type='conversation',
                source_id=str(conversation.id), status='succeeded', output_summary={'result': 'New output'})
            Run.objects.filter(pk=new_run.pk).update(created_at=timezone.now() + timedelta(seconds=1))
            project_terminal_run(new_run.id, new_run.output_summary)
            self.assertEqual(conversation.messages.get(run=new_run).content, 'New output')

    def test_active_runs_block_clear_delete_and_workspace_changes(self):
        for scope in ('default', 'cowork'):
            conversation = self.conversation(scope)
            run = Run.objects.create(organization=self.organization, owner=self.user,
                executor_kind='agent', executor_key='general', source_type='conversation',
                source_id=str(conversation.id), status='running')
            for action in ('clear/', 'delete_conversation/'):
                self.assertEqual(self.client.delete(self.endpoint(conversation, action)).status_code, 409)
            self.assertEqual(self.client.post(self.endpoint(conversation, 'workspace/'),
                {'project_id': None}, format='json').status_code, 409)
            run.status = 'cancelled'
            run.save()
            self.assertEqual(self.client.delete(self.endpoint(conversation, 'delete_conversation/')).status_code, 204)

    def test_catalog_migration_preserves_identity_and_activation(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        from apps.applications.models import Application, ApplicationCategory
        category = ApplicationCategory.objects.create(name='Productivity', slug='unified-productivity')
        application = Application.objects.create(slug='cowork', name='CoWork', category=category,
            organization=self.organization, created_by=self.user, is_active=False)
        migration = import_module('apps.applications.migrations.0013_unify_conversation_catalog')
        editor = SimpleNamespace(connection=connection)
        migration.rename_cowork(apps, editor)
        migration.rename_cowork(apps, editor)
        application.refresh_from_db()
        self.assertEqual(application.name, '对话')
        self.assertEqual(application.slug, 'cowork')
        self.assertFalse(application.is_active)

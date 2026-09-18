from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from apps.projects.models import Project
from apps.users.models import User


class ApplicationWorkspaceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('workspace-owner', password='secret')
        category = ApplicationCategory.objects.create(
            name='Workspace applications', slug='workspace-applications')
        self.application = Application.objects.create(
            category=category,
            name='Copy writer',
            slug='copy-writer-workspace',
            description='Test application workspace',
            created_by=self.user,
            access_scope=Application.AccessScope.ORGANIZATION,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_application_project_allocates_its_own_directory(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            response = self.client.post('/api/v1/projects/', {
                'title': 'Copy run',
                'application_id': self.application.id,
            }, format='json')

            self.assertEqual(response.status_code, 201, response.data)
            project = Project.objects.get(id=response.data['id'])
            expected = (
                Path(directory) / 'organizations' / str(project.organization_id)
                / 'applications'
                / self.application.slug / str(project.id)
            ).resolve()
            self.assertEqual(project.application_id, self.application.id)
            self.assertEqual(
                response.data['application_slug'], self.application.slug)
            self.assertEqual(Path(project.working_directory), expected)
            self.assertEqual(Path(response.data['working_directory']), expected)
            self.assertTrue(expected.is_dir())

    def test_application_project_requires_an_accessible_application(self):
        other = User.objects.create_user('other-owner', password='secret')
        self.application.created_by = other
        self.application.is_public = False
        self.application.access_scope = Application.AccessScope.ADMIN
        self.application.save(update_fields=[
            'created_by', 'is_public', 'access_scope',
        ])

        response = self.client.post('/api/v1/projects/', {
            'title': 'Forbidden run',
            'application_id': self.application.id,
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('application_id', response.data)

    def test_workspace_files_lists_and_previews_generated_files(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            response = self.client.post('/api/v1/projects/', {
                'title': 'File producing chat',
                'application_id': self.application.id,
            }, format='json')
            project = Project.objects.get(id=response.data['id'])
            output = Path(project.working_directory) / 'reports'
            output.mkdir()
            (output / 'summary.md').write_bytes(b'# Summary\nGenerated.')

            listing = self.client.get(
                f'/api/v1/projects/{project.id}/workspace-files/')
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual(listing.data['working_directory'], project.working_directory)
            self.assertEqual(listing.data['file_count'], 1)
            self.assertEqual(
                [item['path'] for item in listing.data['entries']],
                ['reports', 'reports/summary.md'],
            )

            preview = self.client.get(
                f'/api/v1/projects/{project.id}/workspace-files/',
                {'path': 'reports/summary.md'},
            )
            self.assertEqual(preview.status_code, 200, preview.data)
            self.assertEqual(preview.data['preview_kind'], 'text')
            self.assertEqual(preview.data['content'], '# Summary\nGenerated.')

    def test_workspace_file_preview_rejects_path_traversal(self):
        with TemporaryDirectory() as directory, override_settings(
                AGENT_WORKSPACE_ROOT=directory):
            response = self.client.post('/api/v1/projects/', {
                'title': 'Safe chat',
                'application_id': self.application.id,
            }, format='json')
            response = self.client.get(
                f"/api/v1/projects/{response.data['id']}/workspace-files/",
                {'path': '../outside.txt'},
            )
            self.assertEqual(response.status_code, 400)

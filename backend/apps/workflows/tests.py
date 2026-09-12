from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership, Organization
from apps.users.models import User
from modules.catalog.models import (
    ApplicationDeployment, ApplicationDraft, DeploymentEnvironment,
)
from modules.catalog.services import publish_application
from .models import Workflow, WorkflowRun


class WorkflowApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('workflow-owner', password='secret')
        self.organization = Organization.objects.create(
            name='Workflow Studio', slug='workflow-studio', owner=self.user)
        Membership.objects.create(
            organization=self.organization, user=self.user,
            role=Membership.Role.OWNER)
        category = ApplicationCategory.objects.create(
            name='Workflow apps', slug='workflow-apps')
        self.applications = []
        for index in range(2):
            application = Application.objects.create(
                category=category, name=f'App {index}', slug=f'workflow-app-{index}',
                description='Test', created_by=self.user,
                organization=self.organization, kind='task')
            draft = ApplicationDraft.objects.create(
                organization=self.organization, application=application,
                updated_by=self.user, content={
                    'kind': 'task', 'executor_kind': 'media',
                    'executor_key': 'test', 'renderer_key': 'generic-task',
                })
            revision = publish_application(
                application=application, actor=self.user,
                expected_draft_version=draft.version)
            ApplicationDeployment.objects.create(
                organization=self.organization, application=application,
                environment=DeploymentEnvironment.PRODUCTION,
                revision=revision, updated_by=self.user)
            self.applications.append(application)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.headers = {'HTTP_X_ORGANIZATION_ID': str(self.organization.id)}

    def test_create_start_and_manually_select_application(self):
        response = self.client.post('/api/workflows/', {
            'name': 'Content flow',
            'steps': [
                {'application_id': self.applications[0].id,
                 'name': 'First', 'order': 0, 'config': {}},
                {'application_id': self.applications[1].id,
                 'name': 'Second', 'order': 1, 'config': {}},
            ],
        }, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        workflow = Workflow.objects.get(id=response.data['id'])
        self.assertEqual(workflow.steps.count(), 2)

        workspace_context = TemporaryDirectory()
        workspace_root = workspace_context.name
        self.addCleanup(workspace_context.cleanup)
        settings_context = override_settings(AGENT_WORKSPACE_ROOT=workspace_root)
        settings_context.enable()
        self.addCleanup(settings_context.disable)
        response = self.client.post(
            f'/api/workflows/{workflow.id}/start/', {}, format='json',
            **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        run = WorkflowRun.objects.get(id=response.data['id'])
        run.project.refresh_from_db()
        expected_run_directory = (
            Path(workspace_root) / 'organizations' / str(self.organization.id)
            / 'workflows' / str(run.id)
        ).resolve()
        self.assertEqual(Path(run.working_directory), expected_run_directory)
        self.assertEqual(
            Path(run.project.working_directory), expected_run_directory)
        self.assertEqual(run.project.workflow_id, workflow.id)
        self.assertNotIn('workflow_id', run.project.structure)
        self.assertTrue(expected_run_directory.is_dir())
        step_runs = list(run.step_runs.select_related('application'))
        for index, step_run in enumerate(step_runs):
            self.assertEqual(
                step_run.application_revision.application_id,
                step_run.application_id)
            self.assertEqual(
                response.data['step_runs'][index]['application_revision_id'],
                str(step_run.application_revision_id))
            expected = (
                expected_run_directory / 'applications'
                / f'{step_run.order:03d}-{step_run.application.slug}'
            )
            self.assertEqual(Path(step_run.working_directory), expected)
            self.assertTrue(expected.is_dir())
        self.assertEqual(
            Path(response.data['working_directory']), expected_run_directory)
        second = workflow.steps.order_by('order')[1]

        response = self.client.post(
            f'/api/workflows/runs/{run.id}/select-step/',
            {'step_id': str(second.id)}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['selected_step_id'], str(second.id))
        self.assertEqual(
            [item['status'] for item in response.data['step_runs']],
            ['idle', 'active'])

        # 编辑工作流不会改变已经启动的运行；运行使用启动时的步骤快照。
        response = self.client.put(f'/api/workflows/{workflow.id}/', {
            'name': 'Content flow updated',
            'steps': [
                {'application_id': self.applications[0].id,
                 'name': 'Only new step', 'order': 0, 'config': {}},
            ],
        }, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)

        response = self.client.get(
            f'/api/workflows/runs/{run.id}/', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['step_runs']), 2)
        self.assertEqual(response.data['selected_step_id'], str(second.id))
        self.assertEqual(
            response.data['step_runs'][1]['step']['application']['id'],
            self.applications[1].id)

        # 执行记录保留步骤完成状态；重新选择已完成步骤不会丢失状态。
        response = self.client.post(
            f'/api/workflows/runs/{run.id}/complete-step/',
            {'step_id': str(second.id)}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'active')
        self.assertEqual(
            [item['status'] for item in response.data['step_runs']],
            ['idle', 'completed'])

        response = self.client.post(
            f'/api/workflows/runs/{run.id}/select-step/',
            {'step_id': str(second.id)}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['step_runs'][1]['status'], 'completed')

        first_source_id = response.data['step_runs'][0]['step']['id']
        response = self.client.post(
            f'/api/workflows/runs/{run.id}/complete-step/',
            {'step_id': first_source_id}, format='json', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'completed')

        response = self.client.get('/api/workflows/runs/', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        runs = response.data if isinstance(response.data, list) else response.data['results']
        self.assertEqual(len(runs), 1)
        self.assertEqual(str(runs[0]['id']), str(run.id))

        response = self.client.get('/api/projects/', **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        projects = response.data if isinstance(response.data, list) else response.data['results']
        workflow_project = next(
            item for item in projects if item['id'] == run.project_id)
        self.assertEqual(workflow_project['source'], 'workflow')

    def test_start_requires_a_production_deployment_for_every_application(self):
        ApplicationDeployment.objects.filter(
            application=self.applications[1],
            environment=DeploymentEnvironment.PRODUCTION,
        ).delete()
        response = self.client.post('/api/workflows/', {
            'name': 'Partially deployed flow',
            'steps': [
                {'application_id': application.id,
                 'name': application.name, 'order': index, 'config': {}}
                for index, application in enumerate(self.applications)
            ],
        }, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)

        workflow = Workflow.objects.get(id=response.data['id'])
        response = self.client.post(
            f'/api/workflows/{workflow.id}/start/', {}, format='json',
            **self.headers)

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn(self.applications[1].name, response.data['detail'])
        self.assertFalse(WorkflowRun.objects.filter(workflow=workflow).exists())

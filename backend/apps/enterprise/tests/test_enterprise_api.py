import pytest
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied

from apps.enterprise.models import (
    AuditLog,
    AutomationTrigger,
    Connector,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    IdentityProvider,
    Membership,
    ProviderConfig,
)
from apps.enterprise.views import ProviderConfigViewSet
from core.throttles import OrganizationRateThrottle
from apps.enterprise.services import (
    apply_input_guardrails,
    enforce_model_policy,
    execution_governance_snapshot,
    dispatch_automation,
)

pytestmark = pytest.mark.django_db


def test_governance_recursively_redacts_input_and_enforces_model_allowlist():
    user = get_user_model().objects.create_user(username='governance-runtime-owner')
    organization = user.organization_memberships.get().organization
    policy = organization.governance_policy
    policy.allowed_models = ['approved-model']
    policy.require_tool_approval = True
    policy.save(update_fields=['allowed_models', 'require_tool_approval'])

    guarded = apply_input_guardrails(organization, {
        'message': 'contact me at person@example.com',
        'history': ['call 13800138000'],
    })

    assert guarded == {
        'message': 'contact me at [REDACTED]',
        'history': ['call [REDACTED]'],
    }
    assert enforce_model_policy(organization, 'approved-model') == 'approved-model'
    with pytest.raises(PermissionDenied, match='Model is not allowlisted'):
        enforce_model_policy(organization, 'blocked-model')
    assert execution_governance_snapshot(organization)['require_tool_approval'] is True


def authenticated_client(user, organization=None):
    client = APIClient()
    client.force_authenticate(user)
    if organization:
        client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.id))
    return client


def test_user_cannot_register_as_admin():
    client = APIClient()
    response = client.post('/api/v1/auth/register/', {
        'username': 'no-admin', 'email': 'x@example.com',
        'password': 'A-secure-password-123!',
        'password_confirm': 'A-secure-password-123!',
        'role': 'admin',
    }, format='json')
    assert response.status_code == 201
    assert response.data['user']['role'] == 'member'


def test_provider_is_isolated_by_membership():
    User = get_user_model()
    user_a = User.objects.create_user(username='tenant-a', password='p')
    user_b = User.objects.create_user(username='tenant-b', password='p')
    org_a = user_a.organization_memberships.get().organization
    org_b = user_b.organization_memberships.get().organization
    ProviderConfig.objects.create(
        organization=org_b, name='private', base_url='https://example.com/v1')
    response = authenticated_client(user_a, org_a).get('/api/v1/enterprise/providers/')
    assert response.status_code == 200
    values = response.data.get('results', response.data)
    assert values == []


def test_viewer_cannot_create_provider():
    User = get_user_model()
    owner = User.objects.create_user(username='owner-rbac', password='p')
    viewer = User.objects.create_user(username='viewer-rbac', password='p')
    organization = owner.organization_memberships.get().organization
    Membership.objects.create(organization=organization, user=viewer,
                              role=Membership.Role.VIEWER)
    response = authenticated_client(viewer, organization).post(
        '/api/v1/enterprise/providers/',
        {'name': 'blocked', 'base_url': 'https://example.com/v1'}, format='json')
    assert response.status_code == 403


def test_audit_log_requires_organization_auditor_role():
    owner = get_user_model().objects.create_user(username='audit-role-owner')
    viewer = get_user_model().objects.create_user(username='audit-role-viewer')
    organization = owner.organization_memberships.get().organization
    Membership.objects.create(
        organization=organization, user=viewer, role=Membership.Role.VIEWER,
    )
    AuditLog.objects.create(
        organization=organization, actor=owner, action='test.read',
        resource_type='test', resource_id='1', request_id='audit-role-test',
        metadata={'method': 'GET', 'path': '/test', 'status_code': 200},
    )

    denied = authenticated_client(viewer, organization).get(
        '/api/v1/enterprise/audit-logs/'
    )
    membership = Membership.objects.get(organization=organization, user=viewer)
    membership.role = Membership.Role.AUDITOR
    membership.save(update_fields=['role'])
    allowed = authenticated_client(viewer, organization).get(
        '/api/v1/enterprise/audit-logs/'
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_platform_auditor_can_read_all_organizations_but_cannot_mutate_them():
    first_owner = get_user_model().objects.create_user(username='platform-audit-owner-a')
    second_owner = get_user_model().objects.create_user(username='platform-audit-owner-b')
    first = first_owner.organization_memberships.get().organization
    second = second_owner.organization_memberships.get().organization
    auditor = get_user_model().objects.create_user(
        username='platform-auditor', role='auditor',
    )
    AuditLog.objects.create(
        organization=second, actor=second_owner, action='test.read',
        resource_type='test', resource_id='2', request_id='platform-audit-test',
        metadata={'method': 'GET', 'path': '/test', 'status_code': 200},
    )
    client = authenticated_client(auditor, second)

    context = client.get('/api/v1/enterprise/deployment-context/')
    logs = client.get('/api/v1/enterprise/audit-logs/')
    denied = client.patch(
        f'/api/v1/enterprise/organizations/{first.id}/',
        {'name': 'Auditor cannot rename'}, format='json',
    )

    assert context.status_code == 200
    assert {item['id'] for item in context.data['organizations']} >= {
        str(first.id), str(second.id),
    }
    assert logs.status_code == 200
    values = logs.data.get('results', logs.data)
    assert any(item['request_id'] == 'platform-audit-test' for item in values)
    assert denied.status_code == 403


def test_api_key_is_hashed_and_authenticates():
    User = get_user_model()
    user = User.objects.create_user(username='api-user', password='p')
    client = authenticated_client(user)
    created = client.post('/api/v1/auth/me/generate-api-key/', {
        'name': 'ci', 'scopes': ['read']}, format='json')
    assert created.status_code == 201
    raw_key = created.data['api_key']
    from apps.users.models import UserAPIKey
    stored = UserAPIKey.objects.get(id=created.data['id'])
    assert raw_key not in stored.key_hash
    api_client = APIClient()
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    assert api_client.get('/api/v1/auth/me/').status_code == 200


def test_invalid_organization_header_does_not_raise_server_error():
    user = get_user_model().objects.create_user(username='bad-org-header', password='p')
    client = authenticated_client(user)
    client.credentials(HTTP_X_ORGANIZATION_ID='not-a-uuid')
    assert client.get('/api/v1/enterprise/providers/').status_code == 403


def test_untrusted_request_id_is_replaced_before_response_and_audit():
    user = get_user_model().objects.create_user(
        username='safe-request-id-owner', password='p')
    organization = user.organization_memberships.get().organization
    response = authenticated_client(user, organization).post(
        '/api/v1/enterprise/providers/',
        {'name': 'request-id-test', 'base_url': 'https://example.com/v1'},
        format='json',
        HTTP_X_REQUEST_ID='invalid request id\r\n' + ('x' * 200),
    )

    assert response.status_code == 201
    request_id = response['X-Request-ID']
    assert len(request_id) == 32
    assert AuditLog.objects.filter(request_id=request_id).exists()


def test_viewer_cannot_rename_organization():
    User = get_user_model()
    owner = User.objects.create_user(username='org-owner', password='p')
    viewer = User.objects.create_user(username='org-viewer', password='p')
    organization = owner.organization_memberships.get().organization
    Membership.objects.create(organization=organization, user=viewer,
                              role=Membership.Role.VIEWER)
    response = authenticated_client(viewer, organization).patch(
        f'/api/v1/enterprise/organizations/{organization.id}/',
        {'name': 'Hijacked'}, format='json')
    assert response.status_code == 403


def test_scim_provision_update_and_deactivate_user():
    owner = get_user_model().objects.create_user(username='scim-owner', password='p')
    organization = owner.organization_memberships.get().organization
    client = authenticated_client(owner, organization)
    created = client.post('/api/v1/enterprise/scim/v2/Users', {
        'userName': 'scim-user', 'emails': [{'value': 'old@example.com'}],
        'roles': [{'value': Membership.Role.OPERATOR}],
    }, format='json')
    assert created.status_code == 201
    user = get_user_model().objects.get(username='scim-user')
    assert not user.has_usable_password()
    membership = Membership.objects.get(organization=organization, user=user)
    assert membership.role == Membership.Role.OPERATOR
    updated = client.patch(f'/api/v1/enterprise/scim/v2/Users/{user.id}', {
        'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
        'Operations': [{'op': 'replace', 'path': 'active', 'value': False}],
    }, format='json')
    assert updated.status_code == 200
    membership.refresh_from_db()
    assert membership.is_active is False


def test_connector_rejects_private_network(monkeypatch):
    owner = get_user_model().objects.create_user(username='connector-owner', password='p')
    organization = owner.organization_memberships.get().organization
    connector = Connector.objects.create(
        organization=organization, name='unsafe', connector_type='webhook',
        endpoint='https://internal.example.test/hook')
    monkeypatch.setattr('apps.enterprise.services.socket.getaddrinfo', lambda *_args, **_kwargs: [
        (2, 1, 6, '', ('127.0.0.1', 443)),
    ])
    response = authenticated_client(owner, organization).post(
        f'/api/v1/enterprise/connectors/{connector.id}/invoke/', {'event': 'test'}, format='json')
    assert response.status_code == 403


def test_schedule_requires_valid_cron_expression():
    owner = get_user_model().objects.create_user(username='cron-owner', password='p')
    organization = owner.organization_memberships.get().organization
    response = authenticated_client(owner, organization).post(
        '/api/v1/enterprise/automations/', {
            'name': 'bad cron', 'trigger_type': 'schedule', 'target_type': 'agent',
            'target_id': '1', 'schedule': 'not cron',
        }, format='json')
    assert response.status_code == 400


def test_webhook_automation_can_start_workflow(monkeypatch, tmp_path):
    from apps.workflows.models import Workflow
    from modules.execution.application.runs import create_run
    from modules.execution.models import Run

    owner = get_user_model().objects.create_user(username='workflow-hook-owner')
    organization = owner.organization_memberships.get().organization
    workflow = Workflow.objects.create(
        organization=organization,
        owner=owner,
        name='Webhook workflow',
        execution_mode=Workflow.ExecutionMode.AUTOMATIC,
        output_mapping={'article': {'from': 'steps.writer.output.result'}},
    )
    trigger = AutomationTrigger.objects.create(
        organization=organization,
        name='Workflow webhook',
        trigger_type='webhook',
        target_type='workflow',
        target_id=str(workflow.id),
        input_mapping={'audience': 'developers'},
    )
    captured = {}

    monkeypatch.setattr(
        'apps.workflows.views.build_workflow_step_snapshots',
        lambda _workflow, _actor: ([], [{'key': 'writer'}]),
    )

    def fake_start_workflow_run(**kwargs):
        captured.update(kwargs)
        return create_run(
            organization=organization,
            owner=owner,
            executor_kind=Run.ExecutorKind.WORKFLOW,
            executor_key='workflow-dag',
            source_type='workflow',
            source_id=workflow.id,
            definition_snapshot={},
            input_data=kwargs['input_data'],
        ), False

    monkeypatch.setattr(
        'modules.execution.application.start_runs.start_workflow_run',
        fake_start_workflow_run,
    )
    monkeypatch.setattr(
        'apps.projects.services.workspace_paths.workflow_working_directory',
        lambda *_args: str(tmp_path),
    )

    trace = dispatch_automation(trigger, owner, {'topic': 'AI workflow'})

    assert trace.status == trace.Status.QUEUED
    assert captured['input_data'] == {
        'audience': 'developers', 'topic': 'AI workflow',
    }
    assert captured['output_mapping'] == workflow.output_mapping
    run = Run.objects.get(pk=trace.output['run_id'])
    assert run.input['working_directory'] == str(tmp_path)


def test_viewer_can_read_but_cannot_update_governance_and_quota():
    User = get_user_model()
    owner = User.objects.create_user(username='policy-owner', password='p')
    viewer = User.objects.create_user(username='policy-viewer', password='p')
    organization = owner.organization_memberships.get().organization
    Membership.objects.create(organization=organization, user=viewer,
                              role=Membership.Role.VIEWER)
    client = authenticated_client(viewer, organization)
    assert client.get('/api/v1/enterprise/governance/').status_code == 200
    assert client.get('/api/v1/enterprise/quota/').status_code == 200
    assert client.patch('/api/v1/enterprise/governance/current/', {'export_enabled': True},
                        format='json').status_code == 403
    assert client.patch('/api/v1/enterprise/quota/current/', {'hard_limit': False},
                        format='json').status_code == 403


def test_organization_request_rate_limit_is_enforced(monkeypatch):
    cache.clear()
    monkeypatch.setattr(ProviderConfigViewSet, 'throttle_classes',
                        [OrganizationRateThrottle])
    user = get_user_model().objects.create_user(username='rate-owner', password='p')
    organization = user.organization_memberships.get().organization
    quota = organization.quota_policy
    quota.requests_per_minute = 1
    quota.save(update_fields=['requests_per_minute'])
    client = authenticated_client(user, organization)
    assert client.get('/api/v1/enterprise/providers/').status_code == 200
    response = client.get('/api/v1/enterprise/providers/')
    assert response.status_code == 429
    cache.clear()


def test_api_key_accepts_future_expiration_and_rejects_past():
    user = get_user_model().objects.create_user(username='expiring-key', password='p')
    client = authenticated_client(user)
    future = (timezone.now() + timezone.timedelta(days=1)).isoformat()
    created = client.post('/api/v1/auth/me/generate-api-key/', {
        'name': 'temporary', 'expires_at': future}, format='json')
    assert created.status_code == 201
    assert created.data['expires_at'] is not None
    past = (timezone.now() - timezone.timedelta(days=1)).isoformat()
    rejected = client.post('/api/v1/auth/me/generate-api-key/', {
        'name': 'expired', 'expires_at': past}, format='json')
    assert rejected.status_code == 400


def test_oidc_exchange_is_single_use():
    from django.core.cache import cache
    user = get_user_model().objects.create_user(username='sso-exchange-user', password='p')
    refresh = __import__('rest_framework_simplejwt.tokens', fromlist=['RefreshToken']).RefreshToken.for_user(user)
    cache.set('sso-exchange:one-time', {
        'user_id': user.id, 'access': str(refresh.access_token), 'refresh': str(refresh),
    }, timeout=60)
    client = APIClient()
    response = client.post('/api/v1/enterprise/sso/exchange', {'exchange': 'one-time'},
                           format='json')
    assert response.status_code == 200
    assert 'refresh' not in response.data['tokens']
    assert response.cookies['agent_studio_refresh']['httponly']
    assert client.post('/api/v1/enterprise/sso/exchange', {'exchange': 'one-time'},
                       format='json').status_code == 400


def test_oidc_login_uses_pkce_and_state(monkeypatch):
    user = get_user_model().objects.create_user(username='oidc-owner', password='p')
    organization = user.organization_memberships.get().organization
    provider = IdentityProvider.objects.create(
        organization=organization, name='corp', protocol='oidc',
        issuer='https://id.example.com', client_id='client')
    monkeypatch.setattr('apps.enterprise.sso._discovery', lambda _provider: {
        'authorization_endpoint': 'https://id.example.com/authorize',
    })
    response = APIClient().get(f'/api/v1/enterprise/sso/oidc/{provider.id}/login')
    assert response.status_code == 302
    assert 'code_challenge=' in response.url
    assert 'state=' in response.url


def test_public_sso_discovery_matches_exact_domain_only():
    user = get_user_model().objects.create_user(username='discovery-owner', password='p')
    organization = user.organization_memberships.get().organization
    provider = IdentityProvider.objects.create(
        organization=organization, name='corp login', protocol='oidc',
        issuer='https://id.example.com', client_id='client', domains=['example.com'])
    client = APIClient()
    response = client.get('/api/v1/enterprise/sso/discovery', {'domain': 'example.com'})
    assert response.status_code == 200
    assert response.data[0]['id'] == provider.id
    assert client.get('/api/v1/enterprise/sso/discovery', {
        'domain': 'evil-example.com'}).data == []


def test_evaluation_run_pins_revision_and_uses_durable_execution():
    from apps.applications.models import Application, ApplicationCategory
    from apps.enterprise.execution import execute_evaluation
    from modules.catalog.models import ApplicationRevision
    from modules.catalog.services import canonical_content_hash
    from modules.execution.models import Run

    owner = get_user_model().objects.create_user(
        username='evaluation-owner', password='p')
    organization = owner.organization_memberships.get().organization
    category, _ = ApplicationCategory.objects.get_or_create(
        slug='evaluation-targets', defaults={'name': 'Evaluation Targets'})
    application = Application.objects.create(
        organization=organization,
        created_by=owner,
        category=category,
        name='Evaluation Target',
        slug='evaluation-target',
        description='Target',
    )
    content = {'executor_kind': 'media', 'executor_key': 'batch-transcribe'}
    revision = ApplicationRevision.objects.create(
        organization=organization,
        application=application,
        revision_no=1,
        content=content,
        content_hash=canonical_content_hash(content),
        created_by=owner,
    )
    suite = EvaluationSuite.objects.create(
        organization=organization,
        name='Release quality',
        target_type='application',
        target_id=str(application.id),
        evaluators=[{'type': 'exact'}],
        quality_gate={'minimum_score': 1.0},
    )
    case = EvaluationCase.objects.create(
        suite=suite,
        name='happy path',
        input={'text': 'hello'},
        expected={'value': 'ok'},
    )
    client = authenticated_client(owner, organization)

    response = client.post(
        f'/api/v1/enterprise/evaluations/{suite.id}/run/',
        {'target_version': str(revision.id)},
        format='json',
    )

    assert response.status_code == 202, response.data
    evaluation = EvaluationRun.objects.get(pk=response.data['id'])
    root = Run.objects.get(pk=evaluation.execution_run_id)
    assert evaluation.status == 'queued'
    assert evaluation.target_version == str(revision.id)
    assert root.executor_kind == Run.ExecutorKind.EVALUATION
    assert root.definition_snapshot['target_version'] == str(revision.id)
    assert root.definition_snapshot['cases'][0]['id'] == str(case.id)

    class Sink:
        def emit(self, _event_type, _payload):
            pass

    result = execute_evaluation(
        {
            'run_id': str(root.id),
            'organization_id': str(organization.id),
            'definition_snapshot': root.definition_snapshot,
            'input': {'outputs': {str(case.id): {'result': 'ok'}}},
        },
        Sink(),
    )
    evaluation.refresh_from_db()
    assert result['passed'] is True
    assert evaluation.status == 'completed'
    assert evaluation.passed is True

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.exceptions import Throttled
from rest_framework.test import APIClient

from apps.enterprise.models import Membership, UsageRecord
from apps.enterprise.services import enforce_member_token_quota, enforce_quota
from modules.execution.application.runs import create_run
from modules.execution.models import Run


pytestmark = pytest.mark.django_db


@pytest.fixture
def members():
    owner = get_user_model().objects.create_user(username='quota-owner')
    member = get_user_model().objects.create_user(username='quota-member')
    organization = owner.organization_memberships.get().organization
    membership = Membership.objects.create(
        organization=organization, user=member, monthly_token_limit=100,
    )
    return owner, member, organization, membership


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def usage(organization, user, tokens):
    return UsageRecord.objects.create(
        organization=organization, user=user, total_tokens=tokens, resource_type='run',
    )


def test_admin_can_set_clear_and_read_member_quota(members):
    owner, member, organization, membership = members
    usage(organization, member, 25)
    client = client_for(owner)
    url = f'/api/v1/enterprise/organizations/{organization.id}/members/'
    for limit in (200, 0, None):
        response = client.patch(f'{url}{membership.id}/', {'monthly_token_limit': limit}, format='json')
        assert response.status_code == 200
        assert response.data['monthly_token_limit'] == limit
        assert response.data['monthly_tokens_used'] == 25
        membership.refresh_from_db()
        assert membership.monthly_token_limit == limit
    row = next(row for row in client.get(url).data if row['id'] == membership.id)
    assert row['monthly_tokens_used'] == 25
    assert row['monthly_token_limit'] is None


@pytest.mark.parametrize('value', [-1, 1.5, 'bad', 9007199254740992])
def test_invalid_member_quota_is_rejected(members, value):
    owner, _, organization, membership = members
    response = client_for(owner).patch(
        f'/api/v1/enterprise/organizations/{organization.id}/members/{membership.id}/',
        {'monthly_token_limit': value}, format='json',
    )
    assert response.status_code == 400
    membership.refresh_from_db()
    assert membership.monthly_token_limit == 100


def test_member_cannot_change_quota_or_other_organizations(members):
    owner, member, organization, membership = members
    url = f'/api/v1/enterprise/organizations/{organization.id}/members/{membership.id}/'
    assert client_for(member).patch(url, {'monthly_token_limit': None}, format='json').status_code == 403
    other = member.organization_memberships.exclude(organization=organization).get().organization
    assert client_for(owner).patch(
        f'/api/v1/enterprise/organizations/{other.id}/members/{membership.id}/',
        {'monthly_token_limit': None}, format='json',
    ).status_code == 404


def test_owner_quota_is_editable_without_allowing_owner_demotion(members):
    owner, _, organization, _ = members
    membership = organization.memberships.get(user=owner)
    url = f'/api/v1/enterprise/organizations/{organization.id}/members/'
    client = client_for(owner)
    assert client.patch(f'{url}{membership.id}/', {'monthly_token_limit': 500}, format='json').status_code == 200
    assert client.patch(f'{url}{membership.id}/', {'role': 'viewer'}, format='json').status_code == 409
    assert client.delete(f'{url}{membership.id}/').status_code == 409
    assert client.post(url, {'user_id': owner.id, 'role': 'viewer'}, format='json').status_code == 409
    membership.refresh_from_db()
    assert membership.role == Membership.Role.OWNER


def test_membership_cannot_be_reassigned_to_bypass_quota(members):
    owner, _, organization, membership = members
    response = client_for(owner).patch(
        f'/api/v1/enterprise/organizations/{organization.id}/members/{membership.id}/',
        {'user_id': owner.id}, format='json',
    )
    assert response.status_code == 400


def test_add_member_accepts_quota_and_admin_role_can_manage_it(members):
    owner, member, organization, membership = members
    membership.role = Membership.Role.ADMIN
    membership.save()
    newcomer = get_user_model().objects.create_user(username='quota-newcomer')
    response = client_for(member).post(
        f'/api/v1/enterprise/organizations/{organization.id}/members/',
        {'user_id': newcomer.id, 'role': 'viewer', 'monthly_token_limit': 42}, format='json',
    )
    assert response.status_code == 201
    assert response.data['monthly_token_limit'] == 42


def test_monthly_usage_is_scoped_to_member_organization_and_calendar_month(members):
    owner, member, organization, _ = members
    now = timezone.localtime()
    previous = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    old = usage(organization, member, 100)
    UsageRecord.objects.filter(pk=old.pk).update(created_at=previous)
    usage(organization, owner, 200)
    other = member.organization_memberships.exclude(organization=organization).get().organization
    usage(other, member, 200)
    usage(organization, member, 99)
    enforce_member_token_quota(organization, member)
    usage(organization, member, 1)
    with pytest.raises(Throttled, match='Member monthly token quota exceeded'):
        enforce_member_token_quota(organization, member)
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    with patch('apps.enterprise.services.timezone.now', return_value=next_month):
        enforce_member_token_quota(organization, member)


def test_member_limit_is_independent_of_organization_soft_limit(members):
    _, member, organization, membership = members
    policy = organization.quota_policy
    policy.hard_limit = False
    policy.save()
    membership.monthly_token_limit = 0
    membership.save()
    with pytest.raises(Throttled):
        enforce_member_token_quota(organization, member)
    membership.monthly_token_limit = None
    membership.save()
    usage(organization, member, 200)
    enforce_member_token_quota(organization, member)
    policy.hard_limit = True
    policy.monthly_token_limit = 100
    policy.save()
    with pytest.raises(Throttled, match='Monthly token quota exceeded'):
        enforce_quota(organization)


@pytest.mark.parametrize('kind', ['agent', 'application', 'workflow', 'knowledge'])
def test_all_run_creation_enforces_member_quota_without_creating_runs(members, kind):
    _, member, organization, membership = members
    membership.monthly_token_limit = 0
    membership.save()
    with pytest.raises(Throttled):
        create_run(
            organization=organization, owner=member, executor_kind=kind,
            source_type=kind, definition_snapshot={}, input_data={},
        )
    assert not Run.objects.filter(organization=organization).exists()


@pytest.mark.parametrize('endpoint', ['knowledge-search', 'knowledge-answer-runs'])
def test_knowledge_requests_reject_exhausted_member_before_model_call(members, endpoint):
    from apps.knowledge.models import KnowledgeBase

    _, member, organization, membership = members
    membership.monthly_token_limit = 0
    membership.save()
    base = KnowledgeBase.objects.create(
        organization=organization, name='Quota knowledge', embedding_model='embedding-model',
    )
    with patch('apps.knowledge.views._embed_query') as embed:
        response = client_for(member).post(
            f'/api/v1/organizations/{organization.id}/{endpoint}/',
            {'query': 'hello', 'knowledge_base_ids': [base.id]}, format='json',
            HTTP_IDEMPOTENCY_KEY='quota-knowledge-request',
        )
    assert response.status_code == 429
    embed.assert_not_called()

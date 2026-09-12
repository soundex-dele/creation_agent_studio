import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.enterprise.models import Membership, Organization


pytestmark = pytest.mark.django_db


SINGLE_TENANT_SETTINGS = {
    'SINGLE_TENANT_MODE': True,
    'SINGLE_TENANT_ORGANIZATION_ID': '',
    'SINGLE_TENANT_ORGANIZATION_SLUG': 'acme',
    'SINGLE_TENANT_ORGANIZATION_NAME': 'Acme Workspace',
    'SINGLE_TENANT_DEFAULT_ROLE': Membership.Role.VIEWER,
}


@override_settings(**SINGLE_TENANT_SETTINGS)
def test_new_users_share_the_server_selected_organization():
    User = get_user_model()
    owner = User.objects.create_user(username='first-user', password='p')
    viewer = User.objects.create_user(username='second-user', password='p')

    assert Organization.objects.count() == 1
    organization = Organization.objects.get(slug='acme')
    assert organization.owner == owner
    assert Membership.objects.get(
        organization=organization, user=owner).role == Membership.Role.OWNER
    assert Membership.objects.get(
        organization=organization, user=viewer).role == Membership.Role.VIEWER


@override_settings(**SINGLE_TENANT_SETTINGS)
def test_deployment_context_provisions_existing_user_and_ignores_client_tenant():
    with override_settings(SINGLE_TENANT_MODE=False):
        user = get_user_model().objects.create_user(username='existing-user', password='p')
        personal_organization = user.organization_memberships.get().organization

    client = APIClient()
    client.force_authenticate(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(personal_organization.id))
    response = client.get('/api/enterprise/deployment-context/')

    assert response.status_code == 200
    assert response.data['single_tenant_mode'] is True
    assert [item['slug'] for item in response.data['organizations']] == ['acme']
    assert Membership.objects.filter(
        organization__slug='acme', user=user, is_active=True).exists()
    assert client.get('/api/enterprise/providers/').status_code == 200


@override_settings(**SINGLE_TENANT_SETTINGS)
def test_organization_free_api_alias_is_available_only_in_single_tenant_mode():
    user = get_user_model().objects.create_user(username='alias-user', password='p')
    other = Organization.objects.create(
        name='Other', slug='other', owner=user, is_active=True)
    Membership.objects.create(
        organization=other, user=user, role=Membership.Role.OWNER)
    client = APIClient()
    client.force_authenticate(user)

    assert client.get('/api/applications').status_code == 200
    assert client.get(f'/api/organizations/{other.id}/applications').status_code == 403
    with override_settings(SINGLE_TENANT_MODE=False):
        assert client.get('/api/applications').status_code == 404


@override_settings(**SINGLE_TENANT_SETTINGS)
def test_additional_organization_creation_is_disabled():
    user = get_user_model().objects.create_user(username='organization-owner', password='p')
    client = APIClient()
    client.force_authenticate(user)

    response = client.post('/api/enterprise/organizations/', {
        'name': 'Another Organization',
        'slug': 'another-organization',
    }, format='json')

    assert response.status_code == 405
    assert Organization.objects.count() == 1


@override_settings(**SINGLE_TENANT_SETTINGS)
def test_inactive_membership_is_not_automatically_reactivated():
    user = get_user_model().objects.create_user(username='removed-user', password='p')
    membership = user.organization_memberships.get()
    membership.is_active = False
    membership.save(update_fields=['is_active', 'updated_at'])
    client = APIClient()
    client.force_authenticate(user)

    response = client.get('/api/enterprise/deployment-context/')

    assert response.status_code == 200
    assert response.data['organizations'] == []
    membership.refresh_from_db()
    assert membership.is_active is False

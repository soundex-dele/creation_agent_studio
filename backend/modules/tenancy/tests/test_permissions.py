from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from apps.enterprise.models import Membership
from modules.tenancy.permissions import HasPathOrganizationRole


def _request(method, user):
    request = getattr(APIRequestFactory(), method)("/")
    request.user = user
    return request


def _view(organization):
    return SimpleNamespace(kwargs={"organization_id": organization.id})


@pytest.mark.django_db
def test_platform_admin_manages_path_organization_without_membership():
    owner = get_user_model().objects.create_user(username="path-organization-owner")
    organization = owner.organization_memberships.get().organization
    admin = get_user_model().objects.create_user(
        username="path-platform-admin",
        role="admin",
    )
    assert not Membership.objects.filter(
        organization=organization,
        user=admin,
    ).exists()

    permission = HasPathOrganizationRole()
    for method in ("get", "post"):
        request = _request(method, admin)
        assert permission.has_permission(request, _view(organization))
        assert request.organization == organization
        assert request.organization_membership.role == Membership.Role.OWNER


@pytest.mark.django_db
def test_platform_auditor_reads_but_cannot_mutate_path_organization():
    owner = get_user_model().objects.create_user(username="path-audit-owner")
    organization = owner.organization_memberships.get().organization
    auditor = get_user_model().objects.create_user(
        username="path-platform-auditor",
        role="auditor",
    )
    assert not Membership.objects.filter(
        organization=organization,
        user=auditor,
    ).exists()

    permission = HasPathOrganizationRole()
    read_request = _request("get", auditor)
    write_request = _request("post", auditor)

    assert permission.has_permission(read_request, _view(organization))
    assert read_request.organization == organization
    assert read_request.organization_membership.role == Membership.Role.AUDITOR
    assert not permission.has_permission(write_request, _view(organization))

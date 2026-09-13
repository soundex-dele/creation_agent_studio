import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership, Organization

from ..models import AddressBook, Contact


@pytest.fixture
def contact_context(db):
    User = get_user_model()
    owner = User.objects.create_user(username="contact-owner")
    developer = User.objects.create_user(username="contact-developer")
    outsider = User.objects.create_user(username="contact-outsider")
    organization = Organization.objects.create(
        name="Contacts Organization", slug="contacts-organization", owner=owner
    )
    Membership.objects.create(
        organization=organization, user=owner, role=Membership.Role.OWNER
    )
    Membership.objects.create(
        organization=organization, user=developer, role=Membership.Role.DEVELOPER
    )
    category = ApplicationCategory.objects.create(
        name="Office", slug="contact-office"
    )
    application = Application.objects.create(
        organization=organization,
        category=category,
        name="通讯录",
        slug="contacts-test",
        description="Contacts",
        created_by=owner,
        kind=Application.Kind.CUSTOM,
    )
    book = AddressBook.objects.create(
        organization=organization, application=application, name="企业通讯录"
    )
    return {
        "owner": owner,
        "developer": developer,
        "outsider": outsider,
        "organization": organization,
        "application": application,
        "book": book,
    }


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _url(context, contact=None):
    base = (
        f"/api/v1/organizations/{context['organization'].id}/applications/"
        f"{context['application'].id}/contacts"
    )
    return f"{base}/{contact.id}" if contact else base


@pytest.mark.django_db
def test_create_search_and_update_contact(contact_context):
    client = _client(contact_context["developer"])
    created = client.post(
        _url(contact_context),
        {
            "name": "张三",
            "company": "示例科技",
            "department": "研发部",
            "job_title": "工程师",
            "methods": [
                {"kind": "phone", "label": "工作", "value": "13800138000", "is_primary": True},
                {"kind": "email", "value": "zhangsan@example.com", "is_primary": True},
            ],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["version"] == 1
    contact = Contact.objects.get(pk=created.data["id"])
    assert contact.organization_id == contact_context["organization"].id
    assert contact.methods.count() == 2

    searched = client.get(_url(contact_context), {"q": "1380013"})
    assert searched.status_code == 200
    assert searched.data["count"] == 1
    assert searched.data["results"][0]["name"] == "张三"

    updated = client.patch(
        _url(contact_context, contact),
        {"version": 1, "job_title": "高级工程师"},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["job_title"] == "高级工程师"
    assert updated.data["version"] == 2

    stale = client.patch(
        _url(contact_context, contact),
        {"version": 1, "job_title": "覆盖更新"},
        format="json",
    )
    assert stale.status_code == 409


@pytest.mark.django_db
def test_tenant_and_role_boundaries(contact_context):
    outsider = _client(contact_context["outsider"])
    assert outsider.get(_url(contact_context)).status_code == 403

    developer = _client(contact_context["developer"])
    created = developer.post(
        _url(contact_context), {"name": "李四"}, format="json"
    )
    contact = Contact.objects.get(pk=created.data["id"])
    assert developer.delete(_url(contact_context, contact)).status_code == 403

    owner = _client(contact_context["owner"])
    assert owner.delete(_url(contact_context, contact)).status_code == 204
    contact.refresh_from_db()
    assert contact.deleted_at is not None
    assert owner.get(_url(contact_context)).data["count"] == 0


@pytest.mark.django_db
def test_contact_method_validation(contact_context):
    client = _client(contact_context["developer"])
    response = client.post(
        _url(contact_context),
        {
            "name": "王五",
            "methods": [
                {"kind": "phone", "value": "10086", "is_primary": True},
                {"kind": "phone", "value": "10010", "is_primary": True},
            ],
        },
        format="json",
    )
    assert response.status_code == 400
    assert "methods" in response.data

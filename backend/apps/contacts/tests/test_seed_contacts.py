import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.applications.models import Application
from apps.enterprise.models import Membership, Organization

from ..models import AddressBook


@pytest.mark.django_db
def test_seed_contacts_is_idempotent():
    owner = get_user_model().objects.create_user(username="seed-contacts-owner")
    organization = Organization.objects.create(
        name="Seed Contacts", slug="seed-contacts", owner=owner
    )
    Membership.objects.create(
        organization=organization, user=owner, role=Membership.Role.OWNER
    )

    call_command("seed_contacts")
    call_command("seed_contacts")

    application = Application.objects.get(organization=organization, slug="contacts")
    assert application.draft.content["renderer_key"] == "contacts"
    assert application.draft.version == 1
    assert AddressBook.objects.filter(
        organization=organization, application=application
    ).count() == 1

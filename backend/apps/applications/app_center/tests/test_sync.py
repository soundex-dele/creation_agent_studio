import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.applications.models import Application


@pytest.mark.django_db
def test_sync_installs_all_packages_and_only_deploys_development():
    owner = get_user_model().objects.create_user(username="app-center-sync-owner")
    organization = owner.owned_organizations.get()

    call_command("sync_app_center", organization_id=str(organization.id))
    call_command("sync_app_center", organization_id=str(organization.id))

    applications = Application.objects.filter(organization=organization)
    assert set(applications.values_list("slug", flat=True)) >= {
        "batch-transcribe", "case-library", "contacts",
    }
    for application in applications.filter(
        slug__in=("batch-transcribe", "case-library", "contacts")
    ):
        assert application.revisions.count() == 1
        assert application.deployments.filter(environment="development").count() == 1
        assert not application.deployments.filter(environment="production").exists()

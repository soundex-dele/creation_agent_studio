import pytest
from django.contrib.auth import get_user_model

from apps.applications.app_center.discovery import discover_packages
from apps.applications.app_center.installer import sync_package
from apps.applications.models import Application

from ..models import CreationWorkspace


@pytest.mark.django_db
def test_package_installs_workspace(settings):
    owner = get_user_model().objects.create_user(username="toolbox-install-owner")
    organization = owner.owned_organizations.get()
    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
    package = next(item for item in packages if item.manifest.metadata.id == "creation-toolbox")

    sync_package(package, organization)
    sync_package(package, organization)

    application = Application.objects.get(
        organization=organization, slug="creation-toolbox"
    )
    assert CreationWorkspace.objects.filter(
        organization=organization, application=application
    ).count() == 1


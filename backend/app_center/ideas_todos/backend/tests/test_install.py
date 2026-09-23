import shutil

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.applications.app_center.discovery import discover_packages
from apps.applications.models import Application


@pytest.mark.django_db
def test_package_discovery_and_idempotent_install(tmp_path, settings):
    # Validate this real package independently of other in-progress packages.
    shutil.copytree(settings.APP_CENTER_ROOT / "ideas_todos", tmp_path / "ideas_todos")
    settings.APP_CENTER_ROOT = tmp_path
    packages, errors = discover_packages(tmp_path, strict=True)
    assert not errors
    package = next(item for item in packages if item.manifest.metadata.id == "ideas-todos")
    assert package.manifest.spec.database.mode == "django-migrations"
    owner = get_user_model().objects.create_user(username="ideas-install")
    org = owner.owned_organizations.get()
    for _ in range(2):
        call_command("sync_app_center", package_id="ideas-todos", organization_id=str(org.id))
    application = Application.objects.get(organization=org, slug="ideas-todos")
    assert application.name == "想法&待办" and application.is_active
    assert application.visibility == Application.Visibility.ORGANIZATION
    assert application.category.slug == "productivity"
    assert application.draft.content["renderer_key"] == "ideas-todos"
    assert application.revisions.count() == 1 and application.deployments.count() == 1

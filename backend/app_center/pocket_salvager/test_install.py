import shutil

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.applications.app_center.discovery import discover_packages
from apps.applications.models import Application


@pytest.mark.django_db
def test_salvager_catalog_install_is_idempotent(tmp_path, settings):
    shutil.copytree(settings.APP_CENTER_ROOT / "pocket_salvager", tmp_path / "pocket_salvager")
    settings.APP_CENTER_ROOT = tmp_path
    packages, errors = discover_packages(tmp_path, strict=True)
    assert not errors
    assert packages[0].manifest.metadata.id == "pocket-salvager"
    assert packages[0].manifest.spec.database.mode == "none"
    owner = get_user_model().objects.create_user(username="salvager-install")
    organization = owner.owned_organizations.get()
    for _ in range(2):
        call_command("sync_app_center", package_id="pocket-salvager", organization_id=str(organization.id))
    app = Application.objects.get(organization=organization, slug="pocket-salvager")
    assert app.name == "口袋打捞队" and app.is_active
    assert app.category.slug == "games"
    assert app.draft.content["renderer_key"] == "pocket-salvager"
    assert app.revisions.count() == 1 and app.deployments.count() == 1
    client = APIClient()
    client.force_authenticate(owner)
    response = client.get("/api/v1/apps/", {"category": "games", "search": "口袋打捞队"},
                          HTTP_X_ORGANIZATION_ID=str(organization.id))
    assert response.status_code == 200
    data = response.data
    items = data if isinstance(data, list) else data["results"]
    assert len(items) == 1 and items[0]["renderer_key"] == "pocket-salvager"

import shutil

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.applications.app_center.discovery import discover_packages
from apps.applications.models import Application


@pytest.mark.django_db
def test_sokoban_discovery_and_idempotent_install(tmp_path, settings):
    shutil.copytree(settings.APP_CENTER_ROOT / "sokoban", tmp_path / "sokoban")
    settings.APP_CENTER_ROOT = tmp_path
    packages, errors = discover_packages(tmp_path, strict=True)
    assert not errors
    package = packages[0]
    assert package.manifest.metadata.id == "sokoban"
    assert package.manifest.spec.database.mode == "none"
    assert package.manifest.spec.launch_mode == "dedicated"
    owner = get_user_model().objects.create_user(username="sokoban-install")
    org = owner.owned_organizations.get()
    for _ in range(2):
        call_command("sync_app_center", package_id="sokoban", organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug="sokoban")
    assert app.name == "推箱子" and app.is_active
    assert app.category.slug == "games"
    assert app.category.name == "休闲游戏"
    assert app.draft.content["renderer_key"] == "sokoban"
    assert app.draft.content["dependencies"] == {"agents": [], "skills": []}
    assert app.revisions.count() == 1 and app.deployments.count() == 1
    client = APIClient()
    client.force_authenticate(owner)
    response = client.get(
        "/api/v1/apps/", {"category": "games", "search": "推箱子"},
        HTTP_X_ORGANIZATION_ID=str(org.id),
    )
    assert response.status_code == 200
    data = response.data
    items = data if isinstance(data, list) else data["results"]
    assert len(items) == 1
    assert items[0]["slug"] == "sokoban"
    assert items[0]["renderer_key"] == "sokoban"

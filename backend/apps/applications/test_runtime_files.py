import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _client():
    user = get_user_model().objects.create_user(username="runtime-files", password="p")
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_scan_runtime_folder_lists_only_videos(tmp_path, settings):
    settings.APPLICATION_RUNTIME_ALLOWED_ROOTS = [str(tmp_path)]
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "b.txt").write_text("x")

    response = _client().post(
        "/api/apps/runtime-files/scan/",
        {"path": str(tmp_path)},
        format="json",
    )

    assert response.status_code == 200
    assert [item["name"] for item in response.data["videos"]] == ["a.mp4"]


def test_runtime_folder_browser_cannot_escape_configured_root(tmp_path, settings):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    settings.APPLICATION_RUNTIME_ALLOWED_ROOTS = [str(allowed)]

    response = _client().get(
        "/api/apps/runtime-files/list/",
        {"path": str(outside)},
    )

    assert response.status_code == 403

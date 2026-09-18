import pytest
from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage, storages
from django.utils.functional import empty

from core.storage import MEDIA_TOKEN_SALT


@pytest.fixture
def private_media_settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.MEDIA_URL = "/api/v1/media/"
    settings.MEDIA_ACCESS_TTL_SECONDS = 3600
    settings.MEDIA_X_ACCEL_REDIRECT = False
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "core.storage.SignedMediaFileSystemStorage"},
    }
    storages._storages.clear()
    default_storage._wrapped = empty
    yield tmp_path
    storages._storages.clear()
    default_storage._wrapped = empty


def test_signed_media_url_serves_private_file(client, private_media_settings):
    name = default_storage.save("org/image.png", ContentFile(b"png-data"))
    url = default_storage.url(name)

    assert url.startswith("/api/v1/media/?token=")
    response = client.get(url)

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"png-data"
    assert response["Cache-Control"].startswith("private")


def test_private_media_rejects_tampered_or_unsafe_names(client, private_media_settings):
    assert client.get("/api/v1/media/?token=invalid").status_code == 403
    unsafe = signing.dumps(
        {"name": "../secret.txt"}, salt=MEDIA_TOKEN_SALT, compress=True
    )
    assert client.get(f"/api/v1/media/?token={unsafe}").status_code == 403


def test_nginx_acceleration_uses_internal_location(
    client, settings, private_media_settings
):
    name = default_storage.save("org/video.mp4", ContentFile(b"video"))
    url = default_storage.url(name)
    settings.MEDIA_X_ACCEL_REDIRECT = True

    response = client.get(url)

    assert response.status_code == 200
    assert response["X-Accel-Redirect"] == "/_protected_media/org/video.mp4"
    assert response["Content-Length"] == "5"

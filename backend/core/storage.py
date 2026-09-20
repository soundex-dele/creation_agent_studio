"""Private media storage and short-lived preview/download URLs."""

from pathlib import PurePosixPath
from urllib.parse import urlencode

from django.core import signing
from django.core.files.storage import FileSystemStorage
from django.urls import reverse


MEDIA_TOKEN_SALT = "agent-studio.private-media.v1"


def signed_media_url(name, *, filename=None, download=False):
    """Build a short-lived URL without exposing the backing storage path."""
    payload = {"name": str(name)}
    if download:
        safe_filename = PurePosixPath(
            str(filename or name).replace("\\", "/")
        ).name
        payload.update({"download": True, "filename": safe_filename})
    token = signing.dumps(payload, salt=MEDIA_TOKEN_SALT, compress=True)
    base_url = reverse("private-media")
    return f"{base_url}?{urlencode({'token': token})}"


class SignedMediaFileSystemStorage(FileSystemStorage):
    """Keep media private while retaining normal Django FileField semantics."""

    def url(self, name):
        return signed_media_url(name)

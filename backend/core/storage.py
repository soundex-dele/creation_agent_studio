"""Private media storage and short-lived download URLs."""

from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.files.storage import FileSystemStorage


MEDIA_TOKEN_SALT = "agent-studio.private-media.v1"


class SignedMediaFileSystemStorage(FileSystemStorage):
    """Keep media private while retaining normal Django FileField semantics."""

    def url(self, name):
        token = signing.dumps(
            {"name": str(name)},
            salt=MEDIA_TOKEN_SALT,
            compress=True,
        )
        base_url = str(settings.MEDIA_URL).rstrip("/") + "/"
        return f"{base_url}?{urlencode({'token': token})}"

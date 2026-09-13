import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.utils.module_loading import import_string


ARTIFACT_TOKEN_SALT = "creation-agent-studio.artifact-access"


class ArtifactObjectUnavailable(Exception):
    pass


class UnsafeArtifactObjectKey(Exception):
    pass


def artifact_token(artifact):
    return signing.dumps(
        {
            "organization_id": str(artifact.organization_id),
            "run_id": str(artifact.run_id),
            "artifact_id": str(artifact.id),
            "content_hash": artifact.content_hash,
        },
        salt=ARTIFACT_TOKEN_SALT,
        compress=True,
    )


def decode_artifact_token(token):
    return signing.loads(
        token,
        salt=ARTIFACT_TOKEN_SALT,
        max_age=int(getattr(settings, "ARTIFACT_ACCESS_TTL_SECONDS", 300)),
    )


def external_artifact_access_url(*, request, artifact, expires_at):
    factory_path = str(
        getattr(settings, "ARTIFACT_ACCESS_URL_FACTORY", "") or ""
    ).strip()
    if not factory_path:
        return None
    factory = import_string(factory_path)
    return factory(request=request, artifact=artifact, expires_at=expires_at)


def resolve_local_artifact_path(object_key):
    root = Path(settings.ARTIFACT_ROOT).resolve()
    candidate = (root / object_key).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeArtifactObjectKey(
            "Artifact object key escapes the configured storage root"
        ) from exc
    return candidate


def open_local_artifact(artifact):
    path = resolve_local_artifact_path(artifact.object_key)
    if not path.is_file():
        raise ArtifactObjectUnavailable("Artifact object is not available")
    return path.open("rb")


def persist_local_artifact(object_key, content):
    """Atomically persist artifact bytes below the configured local root."""

    if not isinstance(content, bytes):
        raise TypeError("Artifact content must be bytes")
    target = resolve_local_artifact_path(object_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".artifact-", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
    return target

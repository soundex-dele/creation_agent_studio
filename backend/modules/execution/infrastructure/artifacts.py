import os
import tempfile
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.module_loading import import_string


ARTIFACT_TOKEN_SALT = "creation-agent-studio.artifact-access"


class ArtifactObjectUnavailable(Exception):
    pass


class UnsafeArtifactObjectKey(Exception):
    pass


def _safe_object_key(object_key):
    value = str(object_key or "").replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise UnsafeArtifactObjectKey("Artifact object key escapes its storage root")
    return path.as_posix()


class LocalArtifactStorage:
    def _path(self, object_key):
        root = Path(settings.ARTIFACT_ROOT).resolve()
        candidate = (root / _safe_object_key(object_key)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise UnsafeArtifactObjectKey(
                "Artifact object key escapes the configured storage root"
            ) from exc
        return candidate

    def put(self, object_key, content):
        target = self._path(object_key)
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

    def open(self, object_key):
        path = self._path(object_key)
        if not path.is_file():
            raise ArtifactObjectUnavailable("Artifact object is not available")
        return path.open("rb")

    def delete(self, object_key):
        self._path(object_key).unlink(missing_ok=True)

    def access_url(self, object_key, expires_in):
        return None


class S3ArtifactStorage:
    """S3-compatible storage for AWS S3, MinIO and compatible services."""

    def __init__(self):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3 artifact storage requires boto3") from exc
        self.bucket = settings.ARTIFACT_S3_BUCKET
        if not self.bucket:
            raise RuntimeError("ARTIFACT_S3_BUCKET is required for S3 storage")
        self.prefix = str(getattr(settings, "ARTIFACT_S3_PREFIX", "") or "").strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=getattr(settings, "ARTIFACT_S3_ENDPOINT_URL", "") or None,
            region_name=getattr(settings, "ARTIFACT_S3_REGION", "") or None,
            aws_access_key_id=getattr(settings, "ARTIFACT_S3_ACCESS_KEY", "") or None,
            aws_secret_access_key=getattr(settings, "ARTIFACT_S3_SECRET_KEY", "") or None,
        )

    def _key(self, object_key):
        key = _safe_object_key(object_key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, object_key, content):
        self.client.put_object(Bucket=self.bucket, Key=self._key(object_key), Body=content)
        return object_key

    def open(self, object_key):
        try:
            return self.client.get_object(
                Bucket=self.bucket, Key=self._key(object_key)
            )["Body"]
        except self.client.exceptions.NoSuchKey as exc:
            raise ArtifactObjectUnavailable("Artifact object is not available") from exc
        except Exception as exc:
            try:
                from botocore.exceptions import ClientError
            except ImportError:
                raise
            code = str(
                getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            )
            if isinstance(exc, ClientError) and code in {
                "404", "NoSuchKey", "NotFound"
            }:
                raise ArtifactObjectUnavailable(
                    "Artifact object is not available"
                ) from exc
            raise

    def delete(self, object_key):
        self.client.delete_object(Bucket=self.bucket, Key=self._key(object_key))

    def access_url(self, object_key, expires_in):
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(object_key)},
            ExpiresIn=max(1, int(expires_in)),
        )


def get_artifact_storage():
    backend = str(getattr(
        settings,
        "ARTIFACT_STORAGE_BACKEND",
        "modules.execution.infrastructure.artifacts.LocalArtifactStorage",
    )).strip()
    aliases = {
        "local": "modules.execution.infrastructure.artifacts.LocalArtifactStorage",
        "s3": "modules.execution.infrastructure.artifacts.S3ArtifactStorage",
    }
    storage_class = import_string(aliases.get(backend, backend))
    return storage_class()


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
    if factory_path:
        factory = import_string(factory_path)
        return factory(request=request, artifact=artifact, expires_at=expires_at)
    return get_artifact_storage().access_url(
        artifact.object_key,
        max(1, int((expires_at - timezone.now()).total_seconds())),
    )


def open_artifact(artifact):
    return get_artifact_storage().open(artifact.object_key)


def persist_artifact(object_key, content):
    if not isinstance(content, bytes):
        raise TypeError("Artifact content must be bytes")
    return get_artifact_storage().put(object_key, content)


def delete_artifact_object(object_key):
    return get_artifact_storage().delete(object_key)


# Compatibility helpers for local tooling. Runtime code uses the backend-neutral API.
def resolve_local_artifact_path(object_key):
    return LocalArtifactStorage()._path(object_key)


def open_local_artifact(artifact):
    return LocalArtifactStorage().open(artifact.object_key)


def persist_local_artifact(object_key, content):
    return LocalArtifactStorage().put(object_key, content)

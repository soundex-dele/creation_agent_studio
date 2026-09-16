"""Settings for the self-contained Windows desktop distribution."""

from .base import *


DEBUG = False

# The desktop launcher only listens on loopback.  Keep host validation explicit
# because the UI is still served by Django/Daphne over HTTP.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8765",
    "http://localhost:8765",
]
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# Static assets used by Django admin are immutable inside the PyInstaller
# bundle.  User uploads and application data are redirected by the launcher.
STORAGES["staticfiles"] = {
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# A single desktop installation uses SQLite and the database-polling event
# fallback.  It deliberately has no PostgreSQL or Redis runtime dependency.
DATABASE_ENGINE = "sqlite"
REDIS_ENABLED = False
LOCAL_FILE_MANAGER_ENABLED = True
REQUIRED_EXECUTION_WORKER_POOLS = ()
REQUIRE_AUTOMATION_SCHEDULER = False

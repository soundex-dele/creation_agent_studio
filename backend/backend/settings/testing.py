"""Settings used by the automated test suite."""

from .development import *  # noqa: F403


# Static files and the interactive debug toolbar are not part of API tests.
# Removing both also prevents tests that temporarily toggle DEBUG from making
# middleware and URL configuration disagree about the ``djdt`` namespace.
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware not in {
        'whitenoise.middleware.WhiteNoiseMiddleware',
        'debug_toolbar.middleware.DebugToolbarMiddleware',
    }
]


# Most pre-existing tests exercise explicit organization boundaries. Keep that
# baseline deterministic while single-tenant tests enable the deployment mode
# with override_settings.
SINGLE_TENANT_MODE = False
REGISTRATION_ENABLED = True

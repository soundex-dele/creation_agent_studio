"""Settings used by the automated test suite."""

from .development import *  # noqa: F403


# Static files are not served by the Django test client. Keeping WhiteNoise in
# the test middleware only produces a warning before collectstatic has run.
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != 'whitenoise.middleware.WhiteNoiseMiddleware'
]


# Most pre-existing tests exercise explicit organization boundaries. Keep that
# baseline deterministic while single-tenant tests enable the deployment mode
# with override_settings.
SINGLE_TENANT_MODE = False

"""Settings used by the automated test suite."""

from .development import *  # noqa: F403


# Most pre-existing tests exercise explicit organization boundaries. Keep that
# baseline deterministic while single-tenant tests enable the deployment mode
# with override_settings.
SINGLE_TENANT_MODE = False

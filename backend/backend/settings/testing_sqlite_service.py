"""Integration profile: start a service on an EMPTY temporary SQLITE_PATH first.

Run pytest with --reuse-db --ds=backend.settings.testing_sqlite_service.
Never point this profile at a development or production database.
"""

import os
from pathlib import Path

from .testing import *  # noqa: F403

if not os.environ.get('SQLITE_SERVICE_TEST_PATH'):
    raise RuntimeError('SQLITE_SERVICE_TEST_PATH must name an isolated test database')

_test_path = Path(os.environ['SQLITE_SERVICE_TEST_PATH']).resolve()
DATABASES = {'default': {
    'ENGINE': 'core.sqlite_service',
    'NAME': _test_path,
    'OPTIONS': {'transaction_mode': 'IMMEDIATE'},
    'TEST': {'NAME': str(_test_path)},
}}

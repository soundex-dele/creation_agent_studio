"""Production deployment choices, isolated from developer .env and test settings."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytest.importorskip('sentry_sdk', reason='Install requirements/production.txt to test production settings')
BACKEND = Path(__file__).resolve().parents[3]
READ_SETTINGS = """
import json
import decouple
decouple.config = decouple.Config(decouple.RepositoryEmpty())
from backend.settings import production as settings
names = ('DEBUG', 'REMOTE_RELAY_ALLOW_MEMORY', 'SECURE_SSL_REDIRECT',
         'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'JWT_REFRESH_COOKIE_SECURE',
         'SECURE_HSTS_SECONDS', 'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'SECURE_HSTS_PRELOAD')
print(json.dumps({name: getattr(settings, name) for name in names}))
"""


def production_settings(**overrides):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('REMOTE_', 'SECURE_', 'SESSION_COOKIE_', 'CSRF_COOKIE_', 'JWT_REFRESH_COOKIE_'))}
    env.update(SECRET_KEY='test-production-secret-' + 'x' * 50,
               DATABASE_ENGINE='sqlite', REDIS_ENABLED='False', SENTRY_DSN='', OTEL_ENABLED='False')
    env.update(overrides)
    return subprocess.run([sys.executable, '-c', READ_SETTINGS], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize('transport', [
    {'REMOTE_RELAY_ALLOW_MEMORY': 'True'},
    {'REMOTE_RELAY_REDIS_URL': 'redis://127.0.0.1:6379/0'},
])
def test_production_keeps_https_defaults_with_either_transport(transport):
    result = production_settings(**transport)
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings['DEBUG'] is False
    assert settings['SECURE_SSL_REDIRECT'] is True
    assert settings['SESSION_COOKIE_SECURE'] is True
    assert settings['CSRF_COOKIE_SECURE'] is True
    assert settings['JWT_REFRESH_COOKIE_SECURE'] is True
    assert settings['SECURE_HSTS_SECONDS'] == 31536000


def test_production_http_memory_requires_no_debug_or_redis():
    result = production_settings(REMOTE_RELAY_ALLOW_MEMORY='True', SECURE_SSL_REDIRECT='False')
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings['REMOTE_RELAY_ALLOW_MEMORY'] is True
    assert not any(value for key, value in settings.items() if key != 'REMOTE_RELAY_ALLOW_MEMORY')


def test_production_memory_must_be_explicitly_enabled():
    result = production_settings()
    assert result.returncode != 0
    assert 'REMOTE_RELAY_ALLOW_MEMORY=True for a single ASGI process' in result.stderr


def test_http_preserves_explicit_secure_cookie_override():
    result = production_settings(REMOTE_RELAY_ALLOW_MEMORY='True', SECURE_SSL_REDIRECT='False',
                                 JWT_REFRESH_COOKIE_SECURE='True')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['JWT_REFRESH_COOKIE_SECURE'] is True

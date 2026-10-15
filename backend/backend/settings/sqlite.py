"""One SQLite profile shared by base and development settings."""

from pathlib import Path

from decouple import config


def sqlite_database(base_dir):
    service_enabled = config('SQLITE_SERVICE_ENABLED', default=True, cast=bool)
    return {
        'ENGINE': 'core.sqlite_service' if service_enabled else 'django.db.backends.sqlite3',
        'NAME': Path(config('SQLITE_PATH', default=str(base_dir / 'db.sqlite3'))),
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'timeout': config('SQLITE_BUSY_TIMEOUT_SECONDS', default=5, cast=int),
            'transaction_mode': 'IMMEDIATE' if service_enabled else None,
        },
    }

"""
Development settings for Agent Studio backend.
"""
from .base import *

DEBUG = True

# API quotas protect deployed environments, but make local UI development
# brittle because hot reloads and React StrictMode can issue extra requests.
# Set the environment variable to True when throttling needs local testing.
API_RATE_THROTTLING_ENABLED = config(
    'API_RATE_THROTTLING_ENABLED', default=False, cast=bool)
if not API_RATE_THROTTLING_ENABLED:
    REST_FRAMEWORK = {
        **REST_FRAMEWORK,
        'DEFAULT_THROTTLE_CLASSES': [],
    }

# Show Django Debug Toolbar
INSTALLED_APPS = INSTALLED_APPS + ['debug_toolbar']
MIDDLEWARE = MIDDLEWARE + ['debug_toolbar.middleware.DebugToolbarMiddleware']

INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
]

# SQLite is the supported default Local profile. Set DATABASE_ENGINE=postgresql
# to exercise the Cluster profile with the base settings values.
DATABASE_ENGINE = config('DATABASE_ENGINE', default='sqlite').strip().lower()
REDIS_ENABLED = config(
    'REDIS_ENABLED',
    default=DATABASE_ENGINE in {'postgres', 'postgresql'},
    cast=bool,
)
if DATABASE_ENGINE in {'sqlite', 'sqlite3'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': Path(config('SQLITE_PATH', default=str(BASE_DIR / 'db.sqlite3'))),
            'OPTIONS': {
                'timeout': config('SQLITE_BUSY_TIMEOUT_SECONDS', default=5, cast=int),
            },
        }
    }

LOCAL_FILE_MANAGER_ENABLED = config(
    'LOCAL_FILE_MANAGER_ENABLED',
    default=DATABASE_ENGINE in {'sqlite', 'sqlite3'},
    cast=bool,
)

if not REDIS_ENABLED:
    # SQLite Local and tests are self-contained; DB polling is the cross-process
    # event fallback when no shared Redis channel layer exists.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'agent-studio-development',
        }
    }
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

# More verbose logging
LOGGING['root']['level'] = 'DEBUG'

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Disable CSRF for API development (use with caution)
# CSRF_COOKIE_SECURE = False
# CSRF_SESSION_HTTPONLY = False

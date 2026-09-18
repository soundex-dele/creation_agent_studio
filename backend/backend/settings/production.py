"""
Production settings for Agent Studio backend.
"""
from .base import *
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

if SECRET_KEY == 'django-insecure-change-in-production' or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('SECRET_KEY must be a production secret of at least 50 characters.')
if REDIS_ENABLED and not config('REDIS_PASSWORD', default='').strip():
    raise ImproperlyConfigured('REDIS_PASSWORD must be configured when Redis is enabled.')

# WhiteNoise: serve compressed, cache-busted static files from STATIC_ROOT.
# Requires `python manage.py collectstatic --noinput` to be run during deployment.
STORAGES['staticfiles'] = {
    'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
}
STORAGES['default'] = {
    'BACKEND': 'core.storage.SignedMediaFileSystemStorage',
}
MEDIA_URL = '/api/v1/media/'
REGISTRATION_ENABLED = config('REGISTRATION_ENABLED', default=False, cast=bool)
API_DOCS_ENABLED = config('API_DOCS_ENABLED', default=False, cast=bool)
DJANGO_ADMIN_ENABLED = config('DJANGO_ADMIN_ENABLED', default=False, cast=bool)
APPLICATION_RUNTIME_ALLOW_ALL_PATHS = config(
    'APPLICATION_RUNTIME_ALLOW_ALL_PATHS', default=False, cast=bool)
CREATION_MASTER_ALLOW_ALL_PATHS = config(
    'CREATION_MASTER_ALLOW_ALL_PATHS', default=False, cast=bool)

# Security settings
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
JWT_REFRESH_COOKIE_SECURE = config(
    'JWT_REFRESH_COOKIE_SECURE', default=True, cast=bool)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Allowed hosts should be set from environment
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Sentry integration
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn=config('SENTRY_DSN', default=None),
    integrations=[DjangoIntegration()],
    traces_sample_rate=0.1,
    send_default_pii=False,
)

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        # Containers write structured lifecycle logs to stdout; the runtime's
        # logging driver is responsible for rotation and retention.
        'handlers': ['console'],
        'level': 'WARNING',
    },
}

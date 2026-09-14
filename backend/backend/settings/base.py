"""
Base settings for Creation Agent Studio backend.
"""
import json
from pathlib import Path
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Deployment tenancy. A private single-enterprise installation is the default;
# multi-tenant operators must opt in explicitly with SINGLE_TENANT_MODE=False.
# The organization boundary remains canonical internally without requiring
# clients to select or send an organization identifier on every request.
SINGLE_TENANT_MODE = config('SINGLE_TENANT_MODE', default=True, cast=bool)
SINGLE_TENANT_ORGANIZATION_ID = config(
    'SINGLE_TENANT_ORGANIZATION_ID', default='').strip()
SINGLE_TENANT_ORGANIZATION_SLUG = config(
    'SINGLE_TENANT_ORGANIZATION_SLUG', default='enterprise').strip()
SINGLE_TENANT_ORGANIZATION_NAME = config(
    'SINGLE_TENANT_ORGANIZATION_NAME', default='Enterprise Workspace').strip()
SINGLE_TENANT_DEFAULT_ROLE = config(
    'SINGLE_TENANT_DEFAULT_ROLE', default='viewer').strip().lower()

DATABASE_ENGINE = config('DATABASE_ENGINE', default='postgresql').strip().lower()
REDIS_ENABLED = config(
    'REDIS_ENABLED',
    default=DATABASE_ENGINE in {'postgres', 'postgresql'},
    cast=bool,
)

# Application definition
INSTALLED_APPS = [
    # Register Daphne's ASGI runserver before Django's staticfiles command so
    # local SSE responses are consumed as asynchronous iterators.
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'channels',
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'dj_rest_auth',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'dj_rest_auth.registration',
    'drf_yasg',
    'django_filters',

    # Local apps
    'apps.users',
    'apps.agents',
    'apps.applications',
    'apps.templates',
    'apps.conversations',
    'apps.projects',
    'apps.marketplace',
    'apps.enterprise',
    'apps.workflows',
    'apps.contacts',

    # Versioning, tenancy helpers and durable execution extend the product apps.
    'modules.tenancy.apps.TenancyConfig',
    'modules.catalog.apps.CatalogConfig',
    'modules.execution.apps.ExecutionConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'modules.tenancy.middleware.TenantDatabaseContextMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.enterprise.middleware.RequestContextMiddleware',
    'core.middleware.RequestLoggingMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

ASGI_APPLICATION = 'backend.asgi.application'

if REDIS_ENABLED:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [(config('REDIS_HOST', default='localhost'),
                           int(config('REDIS_PORT', default='6379')))],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
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
elif DATABASE_ENGINE in {'postgres', 'postgresql'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='creation_studio'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default='postgres'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }
else:
    raise ValueError(
        f'Unsupported DATABASE_ENGINE={DATABASE_ENGINE!r}; expected sqlite or postgresql')

SQLITE_BUSY_TIMEOUT_MS = config(
    'SQLITE_BUSY_TIMEOUT_MS', default=5000, cast=int)
SQLITE_SYNCHRONOUS = config('SQLITE_SYNCHRONOUS', default='FULL')

# Server-controlled executor key -> child entrypoint registry. Revision content
# selects only a key; it can never inject an arbitrary Python import path.
EXECUTION_CHILD_ADAPTERS = config(
    'EXECUTION_CHILD_ADAPTERS',
    default=(
        '{"agent":{"agent-completion":'
        '"apps.agents.execution:execute_agent_completion"},'
        '"media":{"batch-transcribe":'
        '"modules.execution.runtime.builtin:execute_batch_transcribe"},'
        '"workflow":{"workflow-dag":'
        '"modules.execution.runtime.builtin:execute_workflow"},'
        '"evaluation":{"evaluation-suite":'
        '"apps.enterprise.execution:execute_evaluation"}}'
    ),
    cast=json.loads,
)
EXECUTION_DOMAIN_PORT = config(
    'EXECUTION_DOMAIN_PORT',
    default='apps.enterprise.execution_port.DjangoExecutionDomainPort',
)
CATALOG_DOMAIN_PORT = config(
    'CATALOG_DOMAIN_PORT',
    default='apps.applications.catalog_port.DjangoCatalogDomainPort',
)

# OpenTelemetry remains opt-in locally. Deployed environments can point the
# OTLP exporter at a collector to retain HTTP and durable-execution spans.
OTEL_ENABLED = config('OTEL_ENABLED', default=False, cast=bool)
OTEL_SERVICE_NAME = config(
    'OTEL_SERVICE_NAME', default='creation-agent-studio-backend')
OTEL_DEPLOYMENT_ENVIRONMENT = config(
    'OTEL_DEPLOYMENT_ENVIRONMENT', default='development')
OTEL_EXPORTER_OTLP_ENDPOINT = config(
    'OTEL_EXPORTER_OTLP_ENDPOINT', default='')
OTEL_EXPORTER_OTLP_INSECURE = config(
    'OTEL_EXPORTER_OTLP_INSECURE', default=False, cast=bool)
EXECUTION_EVENT_QUEUE_SIZE = config(
    'EXECUTION_EVENT_QUEUE_SIZE', default=1000, cast=int)
EXECUTION_WORKER_MAX_CHILDREN = config(
    'EXECUTION_WORKER_MAX_CHILDREN', default=2, cast=int)
EXECUTION_CHECKPOINT_MAX_BYTES = config(
    'EXECUTION_CHECKPOINT_MAX_BYTES', default=1048576, cast=int)
EXECUTION_WORKFLOW_MAX_PARALLELISM = config(
    'EXECUTION_WORKFLOW_MAX_PARALLELISM', default=4, cast=int)
REQUIRED_EXECUTION_WORKER_POOLS = tuple(
    value.strip()
    for value in config('REQUIRED_EXECUTION_WORKER_POOLS', default='').split(',')
    if value.strip()
)
REQUIRE_AUTOMATION_SCHEDULER = config(
    'REQUIRE_AUTOMATION_SCHEDULER', default=False, cast=bool)

RUN_EVENT_RETENTION_DAYS = config(
    'RUN_EVENT_RETENTION_DAYS', default=30, cast=int)
RUN_EVENT_COMPACTION_BATCH_SIZE = config(
    'RUN_EVENT_COMPACTION_BATCH_SIZE', default=500, cast=int)

ARTIFACT_ROOT = Path(config(
    'ARTIFACT_ROOT', default=str(BASE_DIR / 'artifacts')))
ARTIFACT_STORAGE_BACKEND = config('ARTIFACT_STORAGE_BACKEND', default='local')
ARTIFACT_S3_BUCKET = config('ARTIFACT_S3_BUCKET', default='')
ARTIFACT_S3_PREFIX = config('ARTIFACT_S3_PREFIX', default='')
ARTIFACT_S3_ENDPOINT_URL = config('ARTIFACT_S3_ENDPOINT_URL', default='')
ARTIFACT_S3_REGION = config('ARTIFACT_S3_REGION', default='')
ARTIFACT_S3_ACCESS_KEY = config('ARTIFACT_S3_ACCESS_KEY', default='')
ARTIFACT_S3_SECRET_KEY = config('ARTIFACT_S3_SECRET_KEY', default='')
EXECUTION_ARTIFACT_MAX_BYTES = config(
    'EXECUTION_ARTIFACT_MAX_BYTES', default=100 * 1024 * 1024, cast=int)
ARTIFACT_ACCESS_TTL_SECONDS = config(
    'ARTIFACT_ACCESS_TTL_SECONDS', default=300, cast=int)
ARTIFACT_ACCESS_URL_FACTORY = config(
    'ARTIFACT_ACCESS_URL_FACTORY', default='')

# Cache and event notifications. SQLite Local defaults to in-process adapters;
# database polling remains the execution/event delivery fallback.
if REDIS_ENABLED:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': f"redis://{config('REDIS_HOST', default='localhost')}:{config('REDIS_PORT', default='6379')}/1",
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            }
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'creation-agent-studio-local',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Project-level static assets (served in dev; collected into STATIC_ROOT for prod).
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# Media files (User uploaded content)
MEDIA_URL = 'media/'
MEDIA_ROOT = Path(config('MEDIA_ROOT', default=str(BASE_DIR / 'media')))

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'apps.users.authentication.ScopedAPIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'core.throttles.OrganizationRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': config('ANON_RATE_LIMIT', default='30/minute'),
        'user': config('USER_RATE_LIMIT', default='300/minute'),
    },
}

SWAGGER_SETTINGS = {
    'DEFAULT_INFO': 'backend.schema.api_info',
}

# Deployed environments keep API throttling enabled. Development overrides
# this default so local hot reloads cannot exhaust user or organization quotas.
API_RATE_THROTTLING_ENABLED = config(
    'API_RATE_THROTTLING_ENABLED', default=True, cast=bool)

# CORS configuration
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000'
).split(',')

CORS_ALLOW_CREDENTIALS = True

# JWT Configuration
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',

    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

# Browser refresh tokens never need to be readable by JavaScript. The access
# token remains short lived and in memory; this cookie only reaches auth URLs.
JWT_REFRESH_COOKIE_NAME = config(
    'JWT_REFRESH_COOKIE_NAME', default='creation_refresh')
JWT_REFRESH_COOKIE_PATH = config(
    'JWT_REFRESH_COOKIE_PATH', default='/api/v1/')
JWT_REFRESH_COOKIE_SECURE = config(
    'JWT_REFRESH_COOKIE_SECURE', default=not DEBUG, cast=bool)
JWT_REFRESH_COOKIE_SAMESITE = config(
    'JWT_REFRESH_COOKIE_SAMESITE', default='Strict')
JWT_REFRESH_COOKIE_MAX_AGE = config(
    'JWT_REFRESH_COOKIE_MAX_AGE', default=7 * 24 * 3600, cast=int)

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
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# Custom user model (if needed in the future)
AUTH_USER_MODEL = 'users.User'

# LLM Configuration
DEEPSEEK_API_KEY = config('DEEPSEEK_API_KEY', default='')
DEEPSEEK_BASE_URL = config('DEEPSEEK_BASE_URL', default='https://api.deepseek.com/v1')

# Agent adapter selection. Individual deployed Agent definitions may override
# this with {"adapter": "codex", "model": "..."}.
AGENT_ENGINE_ADAPTER = config('AGENT_ENGINE_ADAPTER', default='codex')

# Optional GraphFlow Agent Engine checkout next to this repository.
_GRAPHFLOW_ROOT = BASE_DIR.parent.parent / 'agent-engine'
GRAPHFLOW_SDK_PATH = config(
    'GRAPHFLOW_SDK_PATH', default=str(_GRAPHFLOW_ROOT / 'sdk' / 'python'))
GRAPHFLOW_WORKFLOW_PATH = config(
    'GRAPHFLOW_WORKFLOW_PATH',
    default=str(_GRAPHFLOW_ROOT / 'examples' / 'agent_workflow.json'),
)
GRAPHFLOW_PROVIDER = config('GRAPHFLOW_PROVIDER', default='openai')
GRAPHFLOW_API_KEY = config('GRAPHFLOW_API_KEY', default=DEEPSEEK_API_KEY)
GRAPHFLOW_BASE_URL = config('GRAPHFLOW_BASE_URL', default=DEEPSEEK_BASE_URL)
GRAPHFLOW_MODEL = config('GRAPHFLOW_MODEL', default=config('DEEPSEEK_MODEL', default='deepseek-chat'))
GRAPHFLOW_ENABLE_STREAMING = config('GRAPHFLOW_ENABLE_STREAMING', default=True, cast=bool)
GRAPHFLOW_ENABLE_PERMISSIONS = config('GRAPHFLOW_ENABLE_PERMISSIONS', default=True, cast=bool)
GRAPHFLOW_ENABLE_SKILLS = config('GRAPHFLOW_ENABLE_SKILLS', default=True, cast=bool)
GRAPHFLOW_SKILLS_DIRECTORY = config(
    'GRAPHFLOW_SKILLS_DIRECTORY',
    default=str(Path.home() / '.graphflow' / 'skills'),
)
GRAPHFLOW_MAX_TURNS = config('GRAPHFLOW_MAX_TURNS', default=100, cast=int)
GRAPHFLOW_TIMEOUT_SECONDS = config('GRAPHFLOW_TIMEOUT_SECONDS', default=300, cast=int)
# Native (C++/spdlog) log level for the GraphFlow Agent Engine SDK. The engine's
# LOG_* calls are a no-op until initialize_logging() runs; 'info' mirrors the
# GUI example. Empty/None disables initialization entirely.
GRAPHFLOW_LOG_LEVEL = config('GRAPHFLOW_LOG_LEVEL', default='info')

# Codex adapter. Direct app-server transport is the default and only requires
# an installed `codex`; the local Python SDK remains an opt-in compatibility path.
_CODEX_ROOT = BASE_DIR.parent.parent / 'codex'
CODEX_TRANSPORT = config('CODEX_TRANSPORT', default='app-server')
CODEX_REPOSITORY_PATH = config(
    'CODEX_REPOSITORY_PATH', default=str(_CODEX_ROOT))
CODEX_SDK_PATH = config(
    'CODEX_SDK_PATH', default=str(_CODEX_ROOT / 'sdk' / 'python' / 'src'))
CODEX_BINARY = config('CODEX_BINARY', default='')
CODEX_MODEL = config('CODEX_MODEL', default='')
CODEX_SANDBOX = config('CODEX_SANDBOX', default='workspace-write')
CODEX_APPROVAL_MODE = config('CODEX_APPROVAL_MODE', default='deny_all')
CODEX_REQUEST_TIMEOUT_SECONDS = config(
    'CODEX_REQUEST_TIMEOUT_SECONDS', default=30, cast=int)
CODEX_SKILLS_DIRECTORY = config(
    'CODEX_SKILLS_DIRECTORY',
    default=str(Path.home() / '.codex' / 'skills'),
)
CODEX_WORKING_DIRECTORY = config(
    'CODEX_WORKING_DIRECTORY', default=str(BASE_DIR.parent))

AGENT_WORKSPACE_ROOT = Path(config(
    'AGENT_WORKSPACE_ROOT', default=str(BASE_DIR / 'agent_workspaces')))

# Server-side applications may only browse and process paths below these roots.
APPLICATION_RUNTIME_ALLOWED_ROOTS = [
    item.strip() for item in config(
        'APPLICATION_RUNTIME_ALLOWED_ROOTS', default='').split(',')
    if item.strip()
]

# Image Generation Configuration (OpenAI-compatible / DALL-E style)
# Used by the AI 绘画 (image-genie) app. Leave IMAGE_API_KEY empty to disable.
IMAGE_API_KEY = config('IMAGE_API_KEY', default='')
IMAGE_BASE_URL = config('IMAGE_BASE_URL', default='https://api.openai.com/v1')
IMAGE_MODEL = config('IMAGE_MODEL', default='dall-e-3')
IMAGE_SIZE = config('IMAGE_SIZE', default='1024x1024')
IMAGE_QUALITY = config('IMAGE_QUALITY', default='standard')

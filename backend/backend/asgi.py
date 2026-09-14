"""ASGI config for Django HTTP and streaming responses."""
import os

import django
from django.core.asgi import get_asgi_application
from modules.execution.telemetry import configure_telemetry

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.development')
configure_telemetry()
django.setup()

application = get_asgi_application()

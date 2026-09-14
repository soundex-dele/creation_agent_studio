"""
WSGI config for Creation Agent Studio backend.
"""
import os
from django.core.wsgi import get_wsgi_application
from modules.execution.telemetry import configure_telemetry

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.base')

configure_telemetry()
application = get_wsgi_application()

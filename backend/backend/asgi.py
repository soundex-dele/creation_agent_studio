"""ASGI config for Django HTTP and streaming responses."""
import os

import django
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.development')
django.setup()

application = get_asgi_application()

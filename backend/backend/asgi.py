"""ASGI config for Django HTTP and streaming responses."""
import os

import django
from django.core.asgi import get_asgi_application
from modules.execution.telemetry import configure_telemetry

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.development')
configure_telemetry()
django.setup()

django_application = get_asgi_application()


async def application(scope, receive, send):
    if scope['type'] == 'websocket':
        if scope.get('path') == '/ws/remote/connector/':
            from apps.remote_access.consumer import connector_socket
            await connector_socket(scope, receive, send)
        else:
            await send({'type': 'websocket.close', 'code': 4404})
    else:
        await django_application(scope, receive, send)

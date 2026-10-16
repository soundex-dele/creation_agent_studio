import asyncio
import hashlib
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import SocketTicket

logger = logging.getLogger(__name__)


@database_sync_to_async
def consume_ticket(raw):
    if not raw or len(raw) > 100:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with transaction.atomic():
        changed = SocketTicket.objects.filter(digest=digest, consumed=False, expires_at__gt=timezone.now(), user__is_active=True).update(consumed=True)
        return SocketTicket.objects.get(pk=digest).user_id if changed else None


@database_sync_to_async
def active_user(user_id):
    return get_user_model().objects.filter(pk=user_id, is_active=True).exists()


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # Credentials travel in the first frame, never in URL/access logs.
        self.user_id = None
        await self.accept()
        self.auth_timeout_task = asyncio.create_task(self.auth_timeout())

    async def auth_timeout(self):
        await asyncio.sleep(5)
        if not self.user_id:
            await self.close(code=4401)

    async def authenticate(self, raw):
        self.user_id = await consume_ticket(raw)
        if not self.user_id:
            logger.info('Community connection rejected')
            await self.close(code=4401)
            return
        self.auth_timeout_task.cancel()
        self.targets = ['community.lobby', f'community.user.{self.user_id}']
        for target in self.targets:
            await self.channel_layer.group_add(target, self.channel_name)
        await self.send_json({'type': 'ready'})
        self.heartbeat_task = asyncio.create_task(self.heartbeat())

    async def heartbeat(self):
        while True:
            await asyncio.sleep(25)
            if not await active_user(self.user_id):
                await self.close(code=4401)
                return
            await self.send_json({'type': 'ping'})

    async def disconnect(self, close_code):
        auth_task = getattr(self, 'auth_timeout_task', None)
        if auth_task:
            auth_task.cancel()
        task = getattr(self, 'heartbeat_task', None)
        if task:
            task.cancel()
        for target in getattr(self, 'targets', []):
            await self.channel_layer.group_discard(target, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # This socket is notification-only; all writes use authenticated REST.
        if not self.user_id:
            raw = content.get('ticket', '') if isinstance(content, dict) else ''
            await self.authenticate(raw if isinstance(raw, str) else '')

    async def chat_changed(self, event):
        if not await active_user(self.user_id):
            await self.close(code=4401)
            return
        # No message content travels over the socket. REST rechecks membership.
        await self.send_json({'type': 'changed', 'room': event['room'], 'version': event['version'], 'event_id': event['event_id']})


def socket_application():
    return OriginValidator(ChatConsumer.as_asgi(), settings.COMMUNITY_CHAT_ALLOWED_ORIGINS)

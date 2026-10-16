import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ...media import object_path
from ...models import Attachment, SocketTicket


class Command(BaseCommand):
    help = 'Remove withdrawn attachments, abandoned uploads older than 24h, and expired connection tickets.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=24)
        candidates = Q(message__withdrawn=True) | Q(message=None, created_at__lt=cutoff)
        removed = 0
        for pk in Attachment.objects.filter(candidates).values_list('pk', flat=True).iterator():
            with transaction.atomic():
                # Serialize against message attachment binding using the room lock.
                item = Attachment.objects.filter(pk=pk).first()
                if not item:
                    continue
                from ...models import Room
                from django.db.models import F
                Room.objects.filter(pk=item.room_id).update(version=F('version'))
                item = Attachment.objects.select_for_update().filter(pk=pk).filter(candidates).first()
                if item:
                    object_path(pk).unlink(missing_ok=True)
                    item.delete()
                    removed += 1
        # Recover files left behind by a process crash before the DB insert.
        root = Path(settings.COMMUNITY_CHAT_ROOT)
        if root.exists():
            for path in root.glob('*.bin'):
                try:
                    pk = uuid.UUID(path.stem)
                except ValueError:
                    continue
                if path.stat().st_mtime < cutoff.timestamp() and not Attachment.objects.filter(pk=pk).exists():
                    path.unlink(missing_ok=True)
        SocketTicket.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(self.style.SUCCESS(f'Removed {removed} community attachments.'))

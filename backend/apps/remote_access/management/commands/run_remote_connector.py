import asyncio
import signal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from modules.execution.infrastructure.coordinator_lock import CoordinatorAlreadyRunning, CoordinatorFileLock


class Command(BaseCommand):
    help = "Run the single local remote-access connector (idle until enabled in settings)."

    def handle(self, *args, **options):
        if not settings.REMOTE_ACCESS_HOST_ENABLED:
            raise CommandError("This deployment does not enable remote host capability")
        from apps.remote_access.connector import run_connector
        from apps.remote_access.models import LocalRemoteConfig

        lock = CoordinatorFileLock(Path(settings.REMOTE_CONNECTOR_LOCK_PATH))
        lock.path = Path(settings.REMOTE_CONNECTOR_LOCK_PATH)

        async def run():
            task = asyncio.create_task(run_connector())
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, task.cancel)
                except NotImplementedError:
                    pass
            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            with lock:
                self.stdout.write("Remote connector started; configuration is managed in Settings.")
                try:
                    asyncio.run(run())
                finally:
                    LocalRemoteConfig.objects.filter(pk=1).update(status="offline", connector_seen_at=None)
        except CoordinatorAlreadyRunning as exc:
            raise CommandError("Another remote connector is already running") from exc

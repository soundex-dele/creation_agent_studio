import asyncio
import signal
import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from modules.execution.infrastructure.coordinator_lock import CoordinatorAlreadyRunning, CoordinatorFileLock


def wait_for_launcher():
    stream = sys.stdin
    if stream is None and os.name == 'nt':
        # Windowed PyInstaller clears sys.stdin even when Popen supplies a pipe.
        import ctypes
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        handle = kernel.GetStdHandle(-10 & 0xffffffff)
        stream = os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), 'r')
    if stream:
        stream.readline()


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
            async def stop_from_launcher():
                await asyncio.to_thread(wait_for_launcher)
                task.cancel()

            stop_task = asyncio.create_task(stop_from_launcher()) if os.environ.get('REMOTE_CONNECTOR_STOP_STDIN') == '1' else None
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, task.cancel)
                except NotImplementedError:
                    pass
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                if stop_task:
                    stop_task.cancel()
                    await asyncio.gather(stop_task, return_exceptions=True)

        try:
            with lock:
                self.stdout.write("Remote connector started; configuration is managed in Settings.")
                try:
                    asyncio.run(run())
                finally:
                    LocalRemoteConfig.objects.filter(pk=1).update(status="offline", connector_seen_at=None)
        except CoordinatorAlreadyRunning as exc:
            raise CommandError("Another remote connector is already running") from exc

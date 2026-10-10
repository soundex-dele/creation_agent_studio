from pathlib import Path
import tempfile
import time
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections
from modules.execution.infrastructure.coordinator_lock import CoordinatorFileLock, CoordinatorAlreadyRunning
from ... import filesystem as fs
from ...worker import interrupt_previous, process_next

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the Windows host-local disk cleaner. --once processes at most one queued task."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        if not fs.supported():
            raise CommandError("磁盘清理 worker 仅支持 Windows。")
        host = fs.host_id()
        # ProgramData is shared by Windows accounts; TEMP is not machine-wide.
        import os
        lock_root = Path(os.environ.get("ProgramData", tempfile.gettempdir())) / "AgentStudio" / "locks"
        lock_path = lock_root / f"disk-cleaner-{host}.db"
        try:
            with CoordinatorFileLock(lock_path):
                recover = True
                while True:
                    try:
                        if recover:
                            interrupt_previous(host)
                            recover = False
                        worked = process_next(host)
                    except OperationalError:
                        # On connection loss or contention, never resume a
                        # possibly interrupted deletion. Reconcile first.
                        close_old_connections()
                        recover = True
                        worked = False
                        logger.warning("Disk cleaner database unavailable; retrying connection, not file deletion.")
                        if options["once"]:
                            raise CommandError("数据库暂时不可用，请稍后重试。") from None
                    if options["once"]:
                        return
                    if not worked:
                        time.sleep(1)
        except CoordinatorAlreadyRunning as exc:
            raise CommandError(str(exc)) from exc

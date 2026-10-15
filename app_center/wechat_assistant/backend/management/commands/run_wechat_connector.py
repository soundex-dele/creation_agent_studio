import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from ...connector import candidates, cycle

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Receive WeChat messages and deliver durable Run results."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--workers", type=int, default=8)

    def handle(self, *args, **options):
        stopped = threading.Event()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stopped.set())
        workers = max(1, min(32, options["workers"]))
        running = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while not stopped.is_set():
                close_old_connections()
                cache.set("wechat-connector", timezone.now().isoformat(), 90)
                for bid, future in list(running.items()):
                    if future.done():
                        try:
                            future.result()
                        except Exception:
                            # Do not log arbitrary upstream bodies or credentials.
                            logger.error("WeChat connector cycle failed; it will retry.")
                        del running[bid]
                for oid, bid in candidates():
                    if bid not in running and len(running) < workers:
                        running[bid] = pool.submit(cycle, oid, bid)
                if options["once"]:
                    for future in running.values():
                        future.result()
                    break
                stopped.wait(1)

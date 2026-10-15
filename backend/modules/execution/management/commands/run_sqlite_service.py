"""Own the local SQLite file before starting any API or worker process."""

import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.sqlite_service.lifecycle import wait_for_service
from core.sqlite_service.server import SQLiteService
from modules.execution.infrastructure.coordinator_lock import CoordinatorAlreadyRunning


class Command(BaseCommand):
    help = 'Run the local SQLite data service (before migrations, API and workers).'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--wait', type=float, default=None,
                            help='Only wait this many seconds for a healthy service.')
        parser.add_argument('--admission-timeout', type=float, default=30)
        parser.add_argument('--transaction-idle-timeout', type=float, default=60)

    def handle(self, *args, **options):
        database = settings.DATABASES['default']
        if database['ENGINE'] != 'core.sqlite_service':
            if options['wait'] is not None:
                return
            raise CommandError('SQLite service backend is not enabled.')
        if options['wait'] is not None:
            try:
                wait_for_service(database['NAME'], options['wait'])
            except Exception as exc:
                raise CommandError('SQLite data service did not become ready.') from exc
            self.stdout.write('SQLite data service is ready.')
            return
        try:
            service = SQLiteService(
                database['NAME'],
                admission_timeout=options['admission_timeout'],
                transaction_idle_timeout=options['transaction_idle_timeout'],
                busy_timeout=database.get('OPTIONS', {}).get('timeout', 5),
                synchronous=getattr(settings, 'SQLITE_SYNCHRONOUS', 'FULL'),
            )
        except CoordinatorAlreadyRunning as exc:
            raise CommandError('Another SQLite data service already owns this database.') from exc
        stopped = threading.Event()
        previous = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: stopped.set())
        thread = threading.Thread(target=service.serve_forever, name='sqlite-service')
        thread.start()
        self.stdout.write('SQLite data service ready (authenticated loopback transport).')
        try:
            while not stopped.wait(0.5):
                if not thread.is_alive():
                    raise CommandError('SQLite data service stopped unexpectedly.')
        finally:
            service.shutdown()
            thread.join()
            service.server_close()
            for signum, handler in previous.items():
                signal.signal(signum, handler)

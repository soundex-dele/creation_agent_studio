import os
import socket
import logging
import signal
import threading
import time
from pathlib import Path
from contextlib import nullcontext

from django.conf import settings
from django.db import connection
from django.core.management.base import BaseCommand, CommandError

from modules.execution.infrastructure.coordinator import (
    ExecutionCoordinator,
    ExecutionCoordinatorSupervisor,
)
from modules.execution.infrastructure.coordinator_lock import (
    CoordinatorAlreadyRunning,
    CoordinatorFileLock,
)
from modules.execution.models import Run
from modules.execution.telemetry import configure_telemetry
from core.sqlite_service.lifecycle import worker_data_service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run a durable execution worker for SQLite or PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-pool",
            choices=(*Run.ExecutorKind.values, "all"),
            default=Run.ExecutorKind.MEDIA,
        )
        parser.add_argument(
            "--max-children",
            type=int,
            default=settings.EXECUTION_WORKER_MAX_CHILDREN,
        )
        parser.add_argument("--lease-seconds", type=int, default=30)
        parser.add_argument("--poll-interval", type=float, default=0.25)
        parser.add_argument("--once", action="store_true")
        parser.add_argument('--startup-gate', default='',
                            help='Start the data service, then wait for this launcher-created file before claiming tasks.')
        parser.add_argument('--startup-gate-timeout', type=float, default=900,
                            help='Maximum seconds to wait for launcher bootstrap (default: 900).')

    def handle(self, *args, **options):
        previous_sigterm = None
        if threading.current_thread() is threading.main_thread():
            def stop_worker(*_):
                raise KeyboardInterrupt

            previous_sigterm = signal.signal(signal.SIGTERM, stop_worker)
        try:
            with worker_data_service(
                connection.settings_dict,
                synchronous=getattr(settings, 'SQLITE_SYNCHRONOUS', 'FULL'),
                report=self.stdout.write,
            ):
                self._run_worker(*args, **options)
        finally:
            if previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)

    def _run_worker(self, *args, **options):
        configure_telemetry()
        database_path = connection.settings_dict.get("NAME")
        if connection.vendor == "sqlite" and (
            not database_path or str(database_path) == ":memory:"
        ):
            raise CommandError("Coordinator requires a file-backed SQLite database")

        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        worker_pools = (
            tuple(Run.ExecutorKind.values)
            if options["worker_pool"] == "all"
            else (options["worker_pool"],)
        )
        coordinators = tuple(
            ExecutionCoordinator(
                worker_id=f"{worker_id}:{worker_pool}",
                worker_pool=worker_pool,
                max_children=options["max_children"],
                lease_seconds=options["lease_seconds"],
                poll_interval=options["poll_interval"],
                adapter_entries=(
                    getattr(settings, "EXECUTION_CHILD_ADAPTERS", {}).get(
                        worker_pool,
                        {},
                    )
                ),
            )
            for worker_pool in worker_pools
        )
        coordinator = ExecutionCoordinatorSupervisor(
            coordinators,
            poll_interval=options["poll_interval"],
        )
        try:
            lock = (
                CoordinatorFileLock(database_path)
                if connection.vendor == "sqlite"
                else nullcontext()
            )
            with lock:
                if options.get('startup_gate'):
                    gate = Path(options['startup_gate'])
                    deadline = time.monotonic() + options.get('startup_gate_timeout', 900)
                    self.stdout.write('Worker data service available; waiting for migrations/bootstrap.')
                    while not gate.is_file():
                        if time.monotonic() >= deadline:
                            raise CommandError('Worker startup gate timed out; bootstrap did not complete.')
                        time.sleep(0.1)
                logger.info("worker state=started worker_id=%s pools=%s max_children=%s adapters=%s",
                            worker_id, ','.join(worker_pools), options['max_children'],
                            sum(len(getattr(settings, 'EXECUTION_CHILD_ADAPTERS', {}).get(pool, {}))
                                for pool in worker_pools))
                self.stdout.write(
                    f"Execution coordinator {worker_id} started "
                    f"for database={connection.vendor} "
                    f"pools={','.join(worker_pools)}"
                )
                if options["once"]:
                    coordinator.run_once()
                else:
                    coordinator.run_forever()
        except CoordinatorAlreadyRunning as exc:
            raise CommandError(str(exc)) from exc
        except KeyboardInterrupt:
            self.stdout.write("Execution coordinator stopping")
        except Exception:
            logger.exception("worker state=failed worker_id=%s", worker_id)
            raise
        finally:
            coordinator.stop()
            logger.info("worker state=stopped worker_id=%s", worker_id)

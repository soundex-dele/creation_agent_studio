import os
import socket
from contextlib import nullcontext

from django.conf import settings
from django.db import connection
from django.core.management.base import BaseCommand, CommandError

from modules.execution.infrastructure.coordinator import ExecutionCoordinator
from modules.execution.infrastructure.coordinator_lock import (
    CoordinatorAlreadyRunning,
    CoordinatorFileLock,
)
from modules.execution.models import Run


class Command(BaseCommand):
    help = "Run a durable execution worker for SQLite or PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-pool",
            choices=Run.ExecutorKind.values,
            default=Run.ExecutorKind.MEDIA,
        )
        parser.add_argument("--max-children", type=int, default=2)
        parser.add_argument("--lease-seconds", type=int, default=30)
        parser.add_argument("--poll-interval", type=float, default=0.25)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        database_path = connection.settings_dict.get("NAME")
        if connection.vendor == "sqlite" and (
            not database_path or str(database_path) == ":memory:"
        ):
            raise CommandError("Coordinator requires a file-backed SQLite database")

        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        coordinator = ExecutionCoordinator(
            worker_id=worker_id,
            worker_pool=options["worker_pool"],
            max_children=options["max_children"],
            lease_seconds=options["lease_seconds"],
            poll_interval=options["poll_interval"],
            adapter_entries=(
                getattr(settings, "EXECUTION_CHILD_ADAPTERS", {}).get(
                    options["worker_pool"],
                    {},
                )
            ),
        )
        try:
            lock = (
                CoordinatorFileLock(database_path)
                if connection.vendor == "sqlite"
                else nullcontext()
            )
            with lock:
                self.stdout.write(
                    f"Execution coordinator {worker_id} started "
                    f"for database={connection.vendor} pool={options['worker_pool']}"
                )
                if options["once"]:
                    coordinator.run_once()
                else:
                    coordinator.run_forever()
        except CoordinatorAlreadyRunning as exc:
            raise CommandError(str(exc)) from exc
        except KeyboardInterrupt:
            self.stdout.write("Execution coordinator stopping")
        finally:
            coordinator.stop()

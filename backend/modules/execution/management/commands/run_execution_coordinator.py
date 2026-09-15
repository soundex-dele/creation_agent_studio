import os
import socket
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

    def handle(self, *args, **options):
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
        finally:
            coordinator.stop()

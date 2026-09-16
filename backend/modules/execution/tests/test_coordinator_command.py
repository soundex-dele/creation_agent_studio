from contextlib import nullcontext
from types import SimpleNamespace

from modules.execution.management.commands import run_execution_coordinator
from modules.execution.models import Run


class _FakeCoordinator:
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.created.append(self)


class _FakeSupervisor:
    created = []

    def __init__(self, coordinators, *, poll_interval):
        self.coordinators = coordinators
        self.poll_interval = poll_interval
        self.ran_once = False
        self.stopped = False
        self.created.append(self)

    def run_once(self):
        self.ran_once = True

    def run_forever(self):
        raise AssertionError("--once should not run forever")

    def stop(self):
        self.stopped = True


def test_all_worker_pool_builds_one_coordinator_per_pool(monkeypatch, tmp_path):
    _FakeCoordinator.created = []
    _FakeSupervisor.created = []
    monkeypatch.setattr(
        run_execution_coordinator,
        "connection",
        SimpleNamespace(
            vendor="sqlite",
            settings_dict={"NAME": tmp_path / "db.sqlite3"},
        ),
    )
    monkeypatch.setattr(
        run_execution_coordinator, "ExecutionCoordinator", _FakeCoordinator
    )
    monkeypatch.setattr(
        run_execution_coordinator,
        "ExecutionCoordinatorSupervisor",
        _FakeSupervisor,
    )
    monkeypatch.setattr(
        run_execution_coordinator,
        "CoordinatorFileLock",
        lambda _path: nullcontext(),
    )
    monkeypatch.setattr(run_execution_coordinator, "configure_telemetry", lambda: None)

    command = run_execution_coordinator.Command()
    command.handle(
        worker_pool="all",
        max_children=2,
        lease_seconds=30,
        poll_interval=0.25,
        once=True,
    )

    assert [
        coordinator.kwargs["worker_pool"]
        for coordinator in _FakeCoordinator.created
    ] == list(Run.ExecutorKind.values)
    assert _FakeSupervisor.created[0].ran_once is True
    assert _FakeSupervisor.created[0].stopped is True


def test_parser_accepts_all_worker_pool():
    parser = run_execution_coordinator.Command().create_parser(
        "manage.py", "run_execution_coordinator"
    )

    options = parser.parse_args(["--worker-pool", "all", "--once"])

    assert options.worker_pool == "all"
    assert options.max_children == 3
    assert options.once is True

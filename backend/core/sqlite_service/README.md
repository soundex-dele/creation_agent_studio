# Worker-owned SQLite data service

SQLite Local uses `core.sqlite_service` as its Django database backend by
default. `run_execution_coordinator` starts the data service in its own process,
before claiming tasks. API, scheduler, connector, management and spawned task
processes use authenticated loopback connections to that service. PostgreSQL
continues to use Django's PostgreSQL backend unchanged.

## Starting the application

From the repository root on Windows:

```powershell
.\backend\venv\Scripts\python.exe backend\manage.py run_execution_coordinator --worker-pool all
# Then start the API in another terminal (or use deploy.ps1 for the full stack).
.\backend\venv\Scripts\python.exe backend\manage.py runserver 0.0.0.0:8080
```

The existing SQLite file is reused; there is no data format conversion. For the
first switch, stop the old API, workers and connectors before starting the new
stack so old direct SQLite connections cannot bypass the queue. Back up the
database using SQLite's backup API or with all processes stopped (include WAL
state when applicable), not by copying an actively written `.sqlite3` file alone.

`deploy.ps1`, `deploy.sh`, and the packaged desktop launcher start the worker
with a unique `--startup-gate` path.
The worker first serves the database, then waits while the launcher migrates the
schema and synchronizes applications. The launcher creates the gate file only
after bootstrap succeeds. Only then may the worker claim tasks. Gate timeout
(900 seconds by default) or bootstrap failure stops the worker. Shutdown order
is reversed so API/connectors stop before the worker and its data service.

`runserver` does not start or own this service. Reloading the API therefore does
not interrupt database sessions in workers or other clients.

For offline maintenance, or a configuration with execution workers disabled:

```powershell
.\backend\venv\Scripts\python.exe backend\manage.py run_sqlite_service
# In another terminal:
.\backend\venv\Scripts\python.exe backend\manage.py migrate
```

`manage.py run_sqlite_service --wait 30` is a readiness check; it never starts a
second service. A worker can reuse an explicitly started service and will not
stop an owner belonging to another process. Ordinary worker use needs no
separate service command. If execution workers are disabled, launchers manage
the maintenance service automatically.

## Transaction contract

- One scheduler admits statements FIFO; a transaction retains ownership from
  BEGIN through COMMIT/ROLLBACK. Nested savepoints retain the same ownership.
  Django atomic blocks use BEGIN IMMEDIATE before taking a read snapshot.
- Each client has an independent native connection **inside the service**.
  Transactions from different clients cannot interleave their writes. Ordinary
  Django ORM operations and existing business idempotency keys remain intact.
- This version routes reads as well as writes through the service, so all ORM
  transactions have one consistent boundary. Reads inside a transaction see its
  uncommitted changes. Standalone SQL reads queue behind an active transaction.
  Expensive computation, model calls and network I/O must stay outside atomic
  blocks. This is serialization, not increased SQLite write capacity.
- Query results are fully materialized server-side before releasing ownership;
  they spill to temporary files beyond 1 MiB. Fetching buffered rows and health
  probes do not wait behind unrelated transactions. This avoids unconsumed
  SELECT/RETURNING cursors retaining hidden SQLite snapshots/write locks.
- Disconnection, worker shutdown or a transaction idle timeout (60 seconds)
  rolls back uncommitted work. Admission waits are bounded (30 seconds), as are
  concurrent sessions (128), cursors per session (128), fetch batches (10,000
  rows), and transport frames (64 MiB). These are explicit failures, not silent
  fallback to direct database access. SQL execution itself has no time budget;
  keep queries and transactions short.
- Transport failures **never transparently replay SQL or COMMIT**. If the reply
  is lost after commit, the result is unknown; reconnect and reconcile with the
  existing business idempotency key / workflow node key before retrying. New
  connections discover the fresh endpoint after a restart. An existing broken
  transaction must be abandoned, not continued on another connection.
- WAL and FULL synchronous are retained. `SQLITE_SYNCHRONOUS` can also select
  NORMAL or EXTRA. `SQLITE_BUSY_TIMEOUT_SECONDS` applies to native handles in
  the service; raising it is not a substitute for correct transaction scope.

The service listens only on `127.0.0.1`, uses a random per-start token, and allows
only its configured database. Its `<database>.service.json` discovery file is
private runtime state, excluded from Git, and restricted to owner access on
POSIX. On Windows it inherits the database directory's ACL: keep that directory
private to the application account. No pickle or arbitrary function dispatch
is accepted. Django SQLite functions and the known sqlite-vec extension are
loaded server-side; arbitrary ATTACH and extension loading are rejected.

`SQLITE_SERVICE_ENABLED=False` explicitly restores the native backend for
offline maintenance/legacy tests. A native Django connection is rejected while
the service's OS file lock is held, even if its transport is busy or unhealthy.
External SQLite tools and old already-open
connections cannot be fenced by Django: stop them before switching modes.
This is a local trusted-process service, not a network SQL API or a tenant
authorization boundary. Existing Django tenancy checks still apply.

## Tests

The reproducible full integration runner creates a temporary database, starts
the worker, runs the suites below, then verifies the bootstrap gate and cleanup:

```powershell
.\backend\venv\Scripts\python.exe backend\scripts\test_sqlite_service.py
```

Run ordinary regression tests with the project virtual environment; the
`backend.settings.testing` profile deliberately keeps native in-memory SQLite:

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest core/tests/test_sqlite_service.py -q
```

Service integration tests must use a **new temporary database**. Set
`DJANGO_SETTINGS_MODULE=backend.settings.testing_sqlite_service` and
`SQLITE_SERVICE_TEST_PATH` to that file in both the worker and test processes.
Start the worker with `--startup-gate <temporary-marker> --once`, then run:

```powershell
.\venv\Scripts\python.exe -m pytest --ds=backend.settings.testing_sqlite_service --reuse-db `
  core/tests/test_sqlite_workflow_concurrency.py `
  modules/execution/tests/test_builtin_runtime.py `
  modules/execution/tests/test_execution_foundation.py `
  modules/execution/tests/test_coordinator.py `
  modules/execution/tests/test_execution_api.py `
  apps/workflows/tests.py apps/knowledge/tests/test_knowledge.py -q
```

The tests migrate that temporary database through the service. After they
finish, create the marker and verify the worker exits successfully and removes
its endpoint. Do not use `--create-db`, in-memory databases, or a real application
database with this integration profile. Never run test teardown against live
application data.

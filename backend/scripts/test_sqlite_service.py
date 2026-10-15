"""Run regression tests against a temporary worker-owned SQLite service.

Invoke with the project venv Python. Optional arguments select pytest targets;
without arguments this runs the data service and affected application suites.
No real application database is opened or reset.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


DEFAULT_TARGETS = [
    'core/tests/test_sqlite_service.py',
    'core/tests/test_sqlite_workflow_concurrency.py',
    'core/tests/test_desktop_sqlite_startup.py',
    'modules/execution/tests/test_builtin_runtime.py',
    'modules/execution/tests/test_execution_foundation.py',
    'modules/execution/tests/test_coordinator.py',
    'modules/execution/tests/test_coordinator_command.py',
    'modules/execution/tests/test_execution_api.py',
    'apps/workflows/tests.py',
    'apps/knowledge/tests/test_knowledge.py',
]


def main():
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='studio-sqlite-service-test-') as directory:
        temporary = Path(directory).resolve()
        database = temporary / 'test.sqlite3'
        gate = temporary / 'bootstrap.ready'
        environment = {
            **os.environ,
            'DJANGO_SETTINGS_MODULE': 'backend.settings.testing_sqlite_service',
            'DATABASE_ENGINE': 'sqlite',
            'SQLITE_SERVICE_ENABLED': 'True',
            'SQLITE_SERVICE_TEST_PATH': str(database),
            'SQLITE_PATH': str(database),
            'PYTHONUNBUFFERED': '1',
        }
        with (temporary / 'worker.log').open('w+', encoding='utf-8') as log:
            worker = subprocess.Popen(
                [sys.executable, 'manage.py', 'run_execution_coordinator', '--worker-pool', 'all',
                 '--startup-gate', str(gate), '--once'],
                cwd=backend, env=environment, stdout=log, stderr=log,
            )
            code = 1
            try:
                subprocess.run(
                    [sys.executable, 'manage.py', 'run_sqlite_service', '--wait', '20'],
                    cwd=backend, env=environment, check=True,
                )
                result = subprocess.run(
                    [sys.executable, '-m', 'pytest', '--ds=backend.settings.testing_sqlite_service',
                     '--reuse-db', *(sys.argv[1:] or DEFAULT_TARGETS), '-q', '--disable-warnings'],
                    cwd=backend, env=environment,
                )
                code = result.returncode
                if code == 0:
                    gate.touch()
                    if worker.wait(timeout=30) != 0:
                        raise RuntimeError('Worker failed after releasing its startup gate')
                    if Path(str(database) + '.service.json').exists():
                        raise RuntimeError('Worker left its service endpoint behind')
                    print('Worker bootstrap gate, final scheduling tick and service cleanup passed.')
            finally:
                if worker.poll() is None:
                    worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
                if code:
                    log.seek(0)
                    print(log.read()[-8000:])
            return code


if __name__ == '__main__':
    raise SystemExit(main())

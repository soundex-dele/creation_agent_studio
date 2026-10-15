import concurrent.futures
import datetime
import decimal
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing

import pytest
from django.db import ConnectionHandler, connections as global_connections, transaction

from core.sqlite_service.client import Connection, endpoint_path
from core.sqlite_service.protocol import VERSION, receive, send
from core.sqlite_service.server import SQLiteService
from core.sqlite_service.lifecycle import worker_data_service, wait_for_service
from modules.execution.infrastructure.coordinator_lock import CoordinatorAlreadyRunning


@pytest.fixture
def service(tmp_path):
    server = SQLiteService(tmp_path / 'test.sqlite3', transaction_idle_timeout=0.5)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def query(connection, sql, params=()):
    with connection.execute(sql, params) as cursor:
        return cursor.fetchall()


def test_service_preserves_types_parameters_functions_and_cursor_batches(service):
    with closing(Connection(service.database)) as db:
        query(db, 'CREATE TABLE example (id INTEGER PRIMARY KEY, label TEXT, payload BLOB, day DATE, stamp DATETIME, flag BOOL, amount DECIMAL)')
        day = datetime.date(2026, 10, 15)
        stamp = datetime.datetime(2026, 10, 15, 1, 2, 3, 123456)
        with db.cursor(django_format=True) as cursor:
            cursor.execute('INSERT INTO example VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                           [1, "中文 ' %s", b'\x00\xff', day, stamp, True, decimal.Decimal('1.25')])
            assert cursor.fetchone() == (1,)
            assert cursor.rowcount == 1
        assert query(db, 'SELECT * FROM example') == [(1, "中文 ' %s", b'\x00\xff', day, stamp, True, 1.25)]
        with db.cursor(django_format=True) as cursor:
            cursor.execute('SELECT %(value)s', {'value': 'bound'})
            assert cursor.fetchone() == ('bound',)
        assert query(db, "SELECT django_date_extract('year', day) FROM example") == [(2026,)]
        with db.cursor() as cursor:
            cursor.executemany('INSERT INTO example (id) VALUES (?)', ((i,) for i in range(2, 1200)))
            assert cursor.rowcount == 1198
            cursor.execute('SELECT id FROM example ORDER BY id')
            assert cursor.fetchmany(2) == [(1,), (2,)]
            assert len(cursor.fetchall()) == 1197


def test_nested_savepoints_rollback_without_releasing_outer_transaction(service):
    with closing(Connection(service.database)) as first, closing(Connection(service.database)) as second:
        query(first, 'CREATE TABLE counts (value INTEGER)')
        query(first, 'BEGIN')
        query(first, 'INSERT INTO counts VALUES (1)')
        query(first, 'SAVEPOINT nested')
        query(first, 'INSERT INTO counts VALUES (2)')
        query(first, 'ROLLBACK TO nested')
        query(first, 'RELEASE nested')
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pending = pool.submit(query, second, 'INSERT INTO counts VALUES (3)')
            time.sleep(0.05)
            assert not pending.done()
            first.commit()
            pending.result(timeout=5)
        assert query(second, 'SELECT value FROM counts ORDER BY value') == [(1,), (3,)]


def test_real_processes_serialize_read_modify_write_transactions(service):
    with closing(Connection(service.database)) as db:
        query(db, 'CREATE TABLE counts (value INTEGER)')
        query(db, 'INSERT INTO counts VALUES (0)')
    code = '''
import sys, time
from core.sqlite_service.client import Connection
c = Connection(sys.argv[1])
try:
    for i in range(12):
        c.execute('BEGIN').close()
        with c.execute('SELECT value FROM counts') as q:
            value = q.fetchone()[0]
        time.sleep(0.002)
        c.execute('UPDATE counts SET value = ?', [value + 1]).close()
        c.commit()
finally:
    c.close()
'''
    processes = [subprocess.Popen([sys.executable, '-c', code, service.database], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stdout + stderr
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
    with closing(Connection(service.database)) as db:
        assert query(db, 'SELECT value FROM counts') == [(48,)]


@pytest.mark.parametrize('abandon', ['disconnect', 'idle'])
def test_abandoned_transaction_is_rolled_back_and_queue_progresses(service, abandon):
    first = Connection(service.database)
    second = Connection(service.database)
    try:
        query(first, 'CREATE TABLE example (value INTEGER)')
        query(first, 'BEGIN')
        query(first, 'INSERT INTO example VALUES (99)')
        if abandon == 'disconnect':
            first.close()
        assert query(second, 'SELECT value FROM example') == []
        query(second, 'INSERT INTO example VALUES (1)')
        assert query(second, 'SELECT value FROM example') == [(1,)]
    finally:
        first.close()
        second.close()


def test_sql_errors_preserve_exception_class_and_transaction_can_rollback(service):
    with closing(Connection(service.database)) as db:
        query(db, 'CREATE TABLE example (id INTEGER PRIMARY KEY)')
        query(db, 'BEGIN')
        query(db, 'INSERT INTO example VALUES (1)')
        with pytest.raises(sqlite3.IntegrityError) as error:
            query(db, 'INSERT INTO example VALUES (1)')
        assert error.value.sqlite_errorname == 'SQLITE_CONSTRAINT_PRIMARYKEY'
        assert db.in_transaction
        db.rollback()
        assert query(db, 'SELECT * FROM example') == []


def test_unconsumed_returning_cursor_does_not_hold_write_lock(service):
    with closing(Connection(service.database)) as a, closing(Connection(service.database)) as b:
        query(a, 'CREATE TABLE example (id INTEGER PRIMARY KEY)')
        cursor = a.execute('INSERT INTO example VALUES (1) RETURNING id')
        query(b, 'INSERT INTO example VALUES (2)')
        assert cursor.fetchone() == (1,)
        cursor.close()


def test_service_authentication_and_singleton(service):
    endpoint = json.loads(endpoint_path(service.database).read_text())
    with socket.create_connection(('127.0.0.1', endpoint['port']), timeout=2) as sock:
        send(sock, {'operation': 'open', 'version': VERSION, 'database': service.database, 'token': 'wrong'})
        with pytest.raises((EOFError, ConnectionError)):
            receive(sock)
    with pytest.raises(CoordinatorAlreadyRunning):
        SQLiteService(service.database)
    with closing(Connection(service.database)) as db:
        with pytest.raises(sqlite3.DatabaseError):
            query(db, "ATTACH DATABASE ':memory:' AS other")
        assert query(db, 'SELECT 1') == [(1,)]


def test_missing_service_never_opens_database_directly(tmp_path):
    path = tmp_path / 'absent.sqlite3'
    with pytest.raises(sqlite3.OperationalError, match='No direct-write fallback'):
        Connection(path)
    assert not path.exists()


def test_worker_owns_service_and_does_not_stop_an_existing_owner(tmp_path):
    path = tmp_path / 'worker.sqlite3'
    config = {'ENGINE': 'core.sqlite_service', 'NAME': path}
    with worker_data_service(config):
        with closing(Connection(path)) as db:
            query(db, 'CREATE TABLE example (value INTEGER)')
        with worker_data_service(config):
            with closing(Connection(path)) as db:
                query(db, 'INSERT INTO example VALUES (1)')
        with closing(Connection(path)) as db:
            assert query(db, 'SELECT value FROM example') == [(1,)]
    assert not endpoint_path(path).exists()
    with pytest.raises(sqlite3.OperationalError):
        Connection(path)


def test_postgresql_worker_does_not_start_sqlite_service(tmp_path):
    with worker_data_service({'ENGINE': 'django.db.backends.postgresql', 'NAME': 'example'}):
        assert not list(tmp_path.iterdir())


def test_worker_serves_database_before_bootstrap_and_cleans_up_on_gate_failure(tmp_path):
    path = tmp_path / 'bootstrap.sqlite3'
    env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings.testing_sqlite_service',
           'SQLITE_SERVICE_TEST_PATH': str(path), 'PYTHONUNBUFFERED': '1'}
    worker = subprocess.Popen(
        [sys.executable, 'manage.py', 'run_execution_coordinator', '--worker-pool', 'all',
         '--startup-gate', str(tmp_path / 'not-ready'), '--startup-gate-timeout', '2'],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        wait_for_service(path, timeout=10)
        with closing(Connection(path)) as db:
            query(db, 'CREATE TABLE bootstrap_probe (id INTEGER)')
        stdout, stderr = worker.communicate(timeout=10)
        assert worker.returncode != 0
        assert 'startup gate timed out' in stderr, stdout + stderr
        assert not endpoint_path(path).exists()
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait()


def test_worker_crash_keeps_commits_and_rolls_back_unfinished_transaction(tmp_path):
    path = tmp_path / 'worker-crash.sqlite3'
    env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings.testing_sqlite_service',
           'SQLITE_SERVICE_TEST_PATH': str(path), 'PYTHONUNBUFFERED': '1'}

    def start():
        return subprocess.Popen(
            [sys.executable, 'manage.py', 'run_execution_coordinator', '--worker-pool', 'all',
             '--startup-gate', str(tmp_path / 'not-ready')],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    worker = start()
    client = None
    try:
        wait_for_service(path, timeout=10)
        client = Connection(path)
        query(client, 'CREATE TABLE example (id INTEGER PRIMARY KEY)')
        query(client, 'INSERT INTO example VALUES (1)')
        query(client, 'BEGIN')
        query(client, 'INSERT INTO example VALUES (2)')
        worker.kill()
        worker.wait(timeout=5)
        with pytest.raises(sqlite3.OperationalError, match='NOT replayed'):
            client.commit()
        # Crash leaves metadata, but the OS singleton lock is released and the
        # next worker replaces the stale endpoint with a new token/session.
        worker = start()
        wait_for_service(path, timeout=10)
        with closing(Connection(path)) as fresh:
            assert query(fresh, 'SELECT id FROM example') == [(1,)]
    finally:
        if client is not None:
            client.close()
        if worker.poll() is None:
            worker.kill()
        worker.wait()


def test_queue_timeout_does_not_execute_an_abandoned_statement(service):
    service.scheduler.timeout = 0.05
    with closing(Connection(service.database)) as first, closing(Connection(service.database)) as second:
        query(first, 'CREATE TABLE example (value INTEGER)')
        query(first, 'BEGIN')
        with pytest.raises(sqlite3.OperationalError, match='queue is busy'):
            query(second, 'INSERT INTO example VALUES (99)')
        first.commit()
        assert query(second, 'SELECT * FROM example') == []
        query(second, 'INSERT INTO example VALUES (1)')


def test_direct_django_backend_cannot_bypass_active_service(service, django_db_blocker):
    from django.core.exceptions import ImproperlyConfigured

    db = ConnectionHandler({'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': service.database}})['default']
    try:
        with django_db_blocker.unblock(), pytest.raises(ImproperlyConfigured, match='direct database access is disabled'):
            db.ensure_connection()
    finally:
        db.close()


def test_service_restart_recovers_commits_but_never_replays_old_connection(tmp_path):
    path = tmp_path / 'restart.sqlite3'
    service = SQLiteService(path)
    thread = threading.Thread(target=service.serve_forever)
    thread.start()
    client = Connection(path)
    query(client, 'CREATE TABLE example (id INTEGER PRIMARY KEY)')
    query(client, 'INSERT INTO example VALUES (1)')
    query(client, 'BEGIN')
    query(client, 'INSERT INTO example VALUES (2)')
    service.shutdown()
    thread.join()
    service.server_close()
    service = SQLiteService(path)
    thread = threading.Thread(target=service.serve_forever)
    thread.start()
    try:
        with pytest.raises(sqlite3.OperationalError, match='NOT replayed'):
            client.commit()
        with closing(Connection(path)) as fresh:
            assert query(fresh, 'SELECT id FROM example') == [(1,)]
    finally:
        client.close()
        service.shutdown()
        thread.join()
        service.server_close()


def test_django_schema_editor_atomic_callbacks_and_knowledge_extension(service, django_db_blocker):
    from django.db import models
    from apps.knowledge.index_backend import load_sqlite_vec

    connections = ConnectionHandler({'default': {'ENGINE': 'core.sqlite_service', 'NAME': service.database}})
    db = connections['default']
    db.alias = 'service_probe'
    global_connections['service_probe'] = db

    class Probe(models.Model):
        text = models.CharField(max_length=30)

        class Meta:
            app_label = 'execution'
            db_table = 'service_probe'

    try:
        with django_db_blocker.unblock():
            with db.schema_editor() as editor:
                editor.create_model(Probe)
            called = []
            with transaction.atomic(using='service_probe'):
                with db.cursor() as cursor:
                    cursor.execute('INSERT INTO service_probe (text) VALUES (%s)', ['中文'])
                db.on_commit(lambda: called.append('committed'))
                assert called == []
            assert called == ['committed']
            with db.cursor() as cursor:
                cursor.execute('SELECT text FROM service_probe')
                assert cursor.fetchone() == ('中文',)
            load_sqlite_vec(db)
            with db.cursor() as cursor:
                cursor.execute('SELECT vec_version()')
                assert cursor.fetchone()[0].startswith('v')
    finally:
        db.close()
        del global_connections['service_probe']

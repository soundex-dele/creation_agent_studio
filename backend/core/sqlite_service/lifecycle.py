"""Explicit service lifetime owned by the worker, never by app import/setup."""

import sqlite3
import threading
import time
from contextlib import contextmanager

from .client import Connection
from .server import SQLiteService
from modules.execution.infrastructure.coordinator_lock import CoordinatorAlreadyRunning


def wait_for_service(database, timeout=30):
    deadline = time.monotonic() + max(0, timeout)
    while True:
        try:
            connection = Connection(database, timeout=min(2, max(0.1, deadline - time.monotonic())))
            connection.close()
            return
        except sqlite3.Error:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


@contextmanager
def worker_data_service(database, *, synchronous='FULL', report=lambda message: None):
    if database.get('ENGINE') != 'core.sqlite_service':
        yield
        return
    try:
        service = SQLiteService(
            database['NAME'],
            busy_timeout=database.get('OPTIONS', {}).get('timeout', 5),
            synchronous=synchronous,
        )
    except CoordinatorAlreadyRunning:
        # Explicitly started maintenance services can be shared. Never stop a
        # service owned by another process, and never replace an unhealthy one.
        wait_for_service(database['NAME'])
        report('SQLite data service: reusing existing owner.')
        yield
        return
    thread = threading.Thread(target=service.serve_forever, name='sqlite-data-service')
    try:
        thread.start()
        report('SQLite data service ready inside worker (single transaction queue).')
        yield
    finally:
        if thread.ident is not None:
            service.shutdown()
            thread.join()
        service.server_close()

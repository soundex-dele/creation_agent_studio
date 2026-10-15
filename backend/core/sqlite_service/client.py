"""Small DB-API proxy. Transport failures are never silently replayed."""

import json
import socket
import sqlite3
import threading
from collections.abc import Mapping
from pathlib import Path

from django.db.backends.sqlite3.base import SQLiteCursorWrapper

from .protocol import VERSION, receive, send


def endpoint_path(database):
    return Path(str(Path(database).resolve()) + ".service.json")


def service_lock(database):
    from modules.execution.infrastructure.coordinator_lock import CoordinatorFileLock

    lock = CoordinatorFileLock(database)
    lock.path = Path(str(Path(database).resolve()) + '.service.lock')
    return lock


def _params(params):
    def adapt(value):
        if value is None or isinstance(value, (int, float, str, bytes, bytearray, memoryview)):
            return value
        return sqlite3.adapt(value)

    if isinstance(params, Mapping):
        return {key: adapt(value) for key, value in params.items()}
    return [adapt(value) for value in params]


class Connection:
    def __init__(self, database, *, timeout=90):
        self.database = str(Path(database).resolve())
        self.closed = False
        self._lock = threading.Lock()
        self._isolation_level = None
        self._in_transaction = False
        self._sqlite_vec_loaded = False
        self._sock = None
        try:
            endpoint = json.loads(endpoint_path(database).read_text(encoding="utf-8"))
            if endpoint["database"] != self.database or endpoint["version"] != VERSION:
                raise ValueError("SQLite service endpoint does not match database/protocol")
            self._sock = socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=timeout)
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._request("open", token=endpoint["token"], database=self.database, version=VERSION)
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            self.close()
            raise sqlite3.OperationalError(
                "SQLite data service unavailable. Start manage.py run_execution_coordinator "
                "--worker-pool all (or run_sqlite_service for maintenance) before API/management "
                "commands. No direct-write fallback is allowed."
            ) from exc

    def _request(self, operation, **payload):
        with self._lock:
            if self.closed:
                raise sqlite3.OperationalError("SQLite service connection is closed")
            try:
                send(self._sock, {"operation": operation, **payload})
                result = receive(self._sock)
            except (OSError, EOFError, ValueError) as exc:
                self.close()
                raise sqlite3.OperationalError(
                    "SQLite service connection lost; transaction outcome may be unknown. "
                    "The request was NOT replayed. Reconcile using the business idempotency key."
                ) from exc
            self._in_transaction = result.get("in_transaction", False)
            if "error" in result:
                detail = result["error"]
                error_type = getattr(sqlite3, detail["type"], sqlite3.DatabaseError)
                if not isinstance(error_type, type) or not issubclass(error_type, sqlite3.Error):
                    error_type = sqlite3.DatabaseError
                error = error_type(detail["message"])
                error.sqlite_errorcode = detail.get("code")
                error.sqlite_errorname = detail.get("name")
                raise error
            return result.get("value")

    @property
    def in_transaction(self):
        return self._in_transaction

    @property
    def isolation_level(self):
        return self._isolation_level

    @isolation_level.setter
    def isolation_level(self, value):
        self._request("isolation_level", value=value)
        self._isolation_level = value

    def cursor(self, *, django_format=False):
        return Cursor(self, django_format=django_format)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._request("commit")

    def rollback(self):
        self._request("rollback")

    def load_sqlite_vec(self):
        if not self._sqlite_vec_loaded:
            self._request("load_sqlite_vec")
            self._sqlite_vec_loaded = True

    def close(self):
        self.closed = True
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None


class Cursor:
    arraysize = 1
    convert_query = SQLiteCursorWrapper.convert_query

    def __init__(self, connection, *, django_format=False):
        self.connection = connection
        self.django_format = django_format
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self._id = None
        self._closed = False

    def _execute(self, sql, params, *, many=False):
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed cursor")
        if self._id is not None:
            self.connection._request("close_cursor", cursor=self._id)
            self._id = None
        example = next(iter(params), None) if many else params
        if self.django_format and params is not None:
            names = list(example) if isinstance(example, Mapping) else None
            sql = self.convert_query(sql, param_names=names)
        result = self.connection._request(
            "execute", sql=sql,
            params=[_params(row) for row in params] if many else _params(params or ()),
            many=many,
        )
        self._id = result["cursor"]
        self.description = tuple(tuple(item) for item in result["description"]) if result["description"] else None
        self.rowcount = result["rowcount"]
        self.lastrowid = result["lastrowid"]
        return self

    def execute(self, sql, params=None):
        return self._execute(sql, params)

    def executemany(self, sql, params):
        return self._execute(sql, list(params), many=True)

    def fetchmany(self, size=None):
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed cursor")
        if self._id is None:
            return []
        result = self.connection._request("fetch", cursor=self._id, size=self.arraysize if size is None else size)
        self.rowcount = result["rowcount"]
        return [tuple(row) for row in result["rows"]]

    def fetchone(self):
        rows = self.fetchmany(1)
        return rows[0] if rows else None

    def fetchall(self):
        result = []
        while rows := self.fetchmany(512):
            result.extend(rows)
        return result

    def close(self):
        if self._id is not None and not self.connection.closed:
            try:
                self.connection._request("close_cursor", cursor=self._id)
            finally:
                self._id = None
        self._closed = True

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            # Match sqlite3 cursor lifetime for connection.execute(...).fetchone().
            # A failed transport already closes and rolls back the session.
            pass

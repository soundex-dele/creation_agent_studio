"""Single-owner SQLite service.

Every statement is scheduled here. A transaction owns the scheduler from BEGIN
through COMMIT/ROLLBACK, including nested savepoints. No application process
opens a writable SQLite handle. Results are spooled before releasing ownership
so a half-consumed SELECT/RETURNING cannot retain a hidden SQLite snapshot/lock.
"""

import hmac
import json
import logging
import os
import secrets
import socket
import socketserver
import sqlite3
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

from django.db.backends.sqlite3._functions import register as register_functions

from .client import endpoint_path, service_lock
from .protocol import VERSION, _decode, _encode, receive, send

logger = logging.getLogger(__name__)


class TransactionScheduler:
    """FIFO admission; the active transaction can finish without re-queuing."""

    def __init__(self, timeout):
        self.timeout = timeout
        self.condition = threading.Condition()
        self.owner = None
        self.waiters = deque()
        self.closed = False

    def acquire(self, session):
        deadline = time.monotonic() + self.timeout
        with self.condition:
            if self.closed:
                raise sqlite3.OperationalError("SQLite service is stopping")
            if self.owner is session:
                return
            ticket = object()
            self.waiters.append(ticket)
            try:
                while self.owner is not None or self.waiters[0] is not ticket:
                    if self.closed:
                        raise sqlite3.OperationalError("SQLite service is stopping")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise sqlite3.OperationalError("SQLite service admission timed out; transaction queue is busy")
                    self.condition.wait(remaining)
                self.owner = session
            finally:
                self.waiters.remove(ticket)
                self.condition.notify_all()

    def release(self, session):
        with self.condition:
            if self.owner is session:
                self.owner = None
                self.condition.notify_all()


class BufferedResult:
    def __init__(self, cursor):
        self.description = cursor.description
        self.lastrowid = cursor.lastrowid
        self.file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        self.buffer = deque()
        try:
            if self.description:
                while rows := cursor.fetchmany(512):
                    self.file.write(json.dumps(rows, default=_encode, ensure_ascii=False).encode("utf-8") + b"\n")
            self.rowcount = cursor.rowcount
            self.file.seek(0)
        except BaseException:
            self.close()
            raise

    def fetch(self, size):
        rows = []
        while len(rows) < size:
            if not self.buffer:
                line = self.file.readline()
                if not line:
                    break
                self.buffer.extend(json.loads(line, object_hook=_decode))
            rows.append(self.buffer.popleft())
        return rows

    def close(self):
        self.file.close()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.db = None
        self.results = {}
        self.next_cursor = 0
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.request.settimeout(5)
        try:
            hello = receive(self.request)
            if (
                hello.get("operation") != "open"
                or hello.get("version") != VERSION
                or hello.get("database") != self.server.database
                or not hmac.compare_digest(str(hello.get("token", "")), self.server.token)
            ):
                return
            self.db = sqlite3.connect(
                self.server.database, isolation_level=None, timeout=self.server.busy_timeout,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            register_functions(self.db)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA legacy_alter_table=OFF")
            self.db.execute(f"PRAGMA synchronous={self.server.synchronous}")
            # These are connection-local settings, not database transactions.
            self.db.set_authorizer(self.authorize)
            self.db.set_progress_handler(lambda: int(self.server.stopping.is_set()), 10000)
            send(self.request, {"value": "ready", "in_transaction": False})
            while True:
                # Poll shutdown portably: shutdown() from another thread doesn't
                # reliably interrupt a timed socket recv on Windows.
                self.request.settimeout(0.25)
                request = receive(
                    self.request,
                    timeout=self.server.transaction_idle_timeout if self.db.in_transaction else None,
                    stop_event=self.server.stopping,
                )
                try:
                    if request['operation'] in {'ping', 'fetch', 'close_cursor'}:
                        # Buffered results and health probes don't touch SQLite
                        # and must not wait behind another client's transaction.
                        value = self.dispatch(request)
                    else:
                        self.server.scheduler.acquire(self)
                        try:
                            value = self.dispatch(request)
                        finally:
                            if not self.db.in_transaction:
                                self.server.scheduler.release(self)
                    response = {"value": value, "in_transaction": self.db.in_transaction}
                except sqlite3.Error as exc:
                    response = {
                        "error": {"type": type(exc).__name__, "message": str(exc),
                                  "code": getattr(exc, "sqlite_errorcode", None),
                                  "name": getattr(exc, "sqlite_errorname", None)},
                        "in_transaction": self.db.in_transaction,
                    }
                self.request.settimeout(30)
                send(self.request, response)
        except (EOFError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            # Disconnects/timeouts abandon the session, never its open transaction.
            logger.debug("SQLite service session disconnected", exc_info=True)
        finally:
            if self.db is not None:
                try:
                    self.db.rollback()
                    self.db.close()
                finally:
                    self.server.scheduler.release(self)
            for result in self.results.values():
                result.close()

    @staticmethod
    def authorize(action, arg1, arg2, database, trigger):
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def dispatch(self, request):
        operation = request["operation"]
        if operation == "ping":
            return "pong"
        if operation == "commit":
            self.db.commit()
        elif operation == "rollback":
            self.db.rollback()
        elif operation == "isolation_level":
            level = request["value"]
            # Even manual autocommit-off clients must acquire the write intent
            # before taking a snapshot. ORM atomic() uses explicit BEGIN.
            self.db.isolation_level = None if level is None else "IMMEDIATE"
        elif operation == "load_sqlite_vec":
            import sqlite_vec

            self.db.enable_load_extension(True)
            try:
                sqlite_vec.load(self.db)
            finally:
                self.db.enable_load_extension(False)
        elif operation == "execute":
            if len(self.results) >= 128:
                raise sqlite3.OperationalError("Too many open SQLite service cursors")
            sql = request["sql"]
            # The Django backend and queue claimant explicitly request
            # IMMEDIATE. Upgrade plain BEGIN as well for raw DB-API clients.
            if sql.strip().rstrip(";").upper() in ("BEGIN", "BEGIN DEFERRED", "BEGIN TRANSACTION"):
                sql = "BEGIN IMMEDIATE"
            cursor = self.db.cursor()
            try:
                if request.get("many"):
                    cursor.executemany(sql, request["params"])
                else:
                    cursor.execute(sql, request["params"])
                result = BufferedResult(cursor)
            finally:
                cursor.close()
            self.next_cursor += 1
            key = self.next_cursor
            if result.description:
                self.results[key] = result
            else:
                result.close()
                key = None
            return {"cursor": key, "description": result.description,
                    "rowcount": result.rowcount, "lastrowid": result.lastrowid}
        elif operation == "fetch":
            size = request["size"]
            if not isinstance(size, int) or not 0 <= size <= 10000:
                raise sqlite3.ProgrammingError("fetch size must be between 0 and 10000")
            result = self.results[request["cursor"]]
            return {"rows": result.fetch(size), "rowcount": result.rowcount}
        elif operation == "close_cursor":
            result = self.results.pop(request["cursor"], None)
            if result:
                result.close()
        else:
            raise sqlite3.NotSupportedError("Unsupported SQLite service operation")


class SQLiteService(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = False

    def __init__(self, database, *, admission_timeout=30, transaction_idle_timeout=60,
                 busy_timeout=5, synchronous="FULL", max_sessions=128):
        self.database = str(Path(database).resolve())
        self.token = secrets.token_urlsafe(32)
        self.scheduler = TransactionScheduler(admission_timeout)
        self.transaction_idle_timeout = transaction_idle_timeout
        self.busy_timeout = busy_timeout
        self.synchronous = synchronous.upper()
        self.stopping = threading.Event()
        if self.synchronous not in {"FULL", "NORMAL", "EXTRA"}:
            raise ValueError("SQLite service synchronous must be FULL, NORMAL or EXTRA")
        self._sessions = threading.BoundedSemaphore(max_sessions)
        self._requests = set()
        self._requests_lock = threading.Lock()
        self._lock = service_lock(self.database)
        self._lock.acquire()
        try:
            with sqlite3.connect(self.database, timeout=busy_timeout) as db:
                mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if mode != "wal":
                    raise RuntimeError("SQLite data service requires WAL mode")
            db.close()
            super().__init__(("127.0.0.1", 0), Handler)
            path = endpoint_path(database)
            temporary = path.with_name(path.name + ".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": VERSION, "database": self.database,
                           "port": self.server_address[1], "token": self.token,
                           "pid": os.getpid()}, stream)
            os.replace(temporary, path)
        except BaseException:
            self._lock.release()
            raise

    def process_request(self, request, client_address):
        if not self._sessions.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self._requests_lock:
            self._requests.add(request)
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._requests_lock:
                self._requests.discard(request)
            self._sessions.release()

    def server_close(self):
        self.stopping.set()
        with self.scheduler.condition:
            self.scheduler.closed = True
            self.scheduler.condition.notify_all()
        with self._requests_lock:
            for request in self._requests:
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()
        endpoint_path(self.database).unlink(missing_ok=True)
        self._lock.release()

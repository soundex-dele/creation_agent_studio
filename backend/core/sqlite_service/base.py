"""Django SQLite backend whose connections live exclusively in the service."""

from django.core.exceptions import ImproperlyConfigured
from django.db.backends.sqlite3.base import DatabaseWrapper as SQLiteDatabaseWrapper
from django.utils.asyncio import async_unsafe

from .client import Connection


class DatabaseWrapper(SQLiteDatabaseWrapper):
    @async_unsafe
    def get_new_connection(self, conn_params):
        if self.is_in_memory_db():
            raise ImproperlyConfigured("SQLite service requires a file database; use the native backend for in-memory tests")
        self.transaction_mode = "IMMEDIATE"
        conn = Connection(conn_params["database"])
        for command in self.init_commands:
            if command.strip():
                with conn.execute(command) as cursor:
                    cursor.fetchall()
        return conn

    def create_cursor(self, name=None):
        return self.connection.cursor(django_format=True)

    def is_usable(self):
        try:
            return self.connection._request("ping") == "pong"
        except self.Database.Error:
            return False

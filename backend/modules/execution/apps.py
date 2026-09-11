import logging
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings
from django.db.backends.signals import connection_created


logger = logging.getLogger(__name__)


def configure_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return

    timeout_ms = int(getattr(settings, "SQLITE_BUSY_TIMEOUT_MS", 5000))
    synchronous = str(getattr(settings, "SQLITE_SYNCHRONOUS", "FULL")).upper()
    if synchronous not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
        raise ValueError(f"Unsupported SQLITE_SYNCHRONOUS value: {synchronous}")

    with connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=%s" % timeout_ms)
        cursor.execute(f"PRAGMA synchronous={synchronous}")

        database_name = str(connection.settings_dict.get("NAME") or "")
        if database_name and database_name != ":memory:":
            cursor.execute("PRAGMA journal_mode=WAL")
            journal_mode = str(cursor.fetchone()[0]).lower()
            if journal_mode != "wal":
                logger.warning(
                    "SQLite database %s did not enter WAL mode (mode=%s)",
                    Path(database_name).resolve(),
                    journal_mode,
                )


class ExecutionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.execution"
    label = "v2_execution"
    verbose_name = "V2 Execution"

    def ready(self):
        connection_created.connect(
            configure_sqlite_connection,
            dispatch_uid="v2_execution.configure_sqlite_connection",
        )

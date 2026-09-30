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
    label = "execution"
    verbose_name = "Durable Execution"

    def ready(self):
        from django.db.models.signals import post_save
        from .event_logging import log_run_event

        post_save.connect(log_run_event, sender="execution.RunEvent",
                          dispatch_uid="execution.log_run_event")
        connection_created.connect(
            configure_sqlite_connection,
            dispatch_uid="execution.configure_sqlite_connection",
        )

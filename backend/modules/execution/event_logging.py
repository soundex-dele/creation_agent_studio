"""Committed lifecycle events, including retries, commands and lease recovery."""

import logging

from django.db import transaction

from core.observability import current_log_context, log_context, _identifier


logger = logging.getLogger(__name__)


def log_run_event(sender, instance, created, raw=False, using=None, **kwargs):
    if not created or raw:
        return
    event_type = instance.type
    # Progress is sampled at the child sink; text/token streams stay in the DB.
    if not event_type.startswith(("run.", "input.", "command.", "workflow.", "supervisor.")):
        return
    if "output." in event_type or event_type.endswith("progress"):
        return
    context = {
        **current_log_context(), "run_id": str(instance.run_id),
        "attempt_id": str(instance.attempt_id or "-"),
        "organization_id": str(instance.organization_id),
    }
    sequence = instance.sequence
    error_code = _identifier((instance.payload or {}).get("error_code", "-"))
    level = (logging.ERROR if event_type.endswith("failed") else logging.WARNING
             if event_type.endswith(("retry_scheduled", "expired")) else logging.INFO)

    def committed():
        with log_context(**context):
            logger.log(level, "execution.event state=committed type=%s sequence=%s error_code=%s",
                       event_type, sequence, error_code)

    transaction.on_commit(committed, using=using)

from contextlib import contextmanager

from django.db import connection, transaction


def set_local_organization(organization_id):
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.organization_id', %s, true)",
            [str(organization_id)],
        )


@contextmanager
def tenant_database_context(organization_id):
    if connection.vendor != "postgresql":
        # SQLite has no session-local RLS variable. Keeping this context out of
        # atomic() is required because its claim path owns a BEGIN IMMEDIATE
        # transaction for deterministic single-writer queue claiming.
        yield
        return

    with transaction.atomic():
        set_local_organization(organization_id)
        yield

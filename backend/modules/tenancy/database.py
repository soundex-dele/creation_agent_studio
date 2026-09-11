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
    with transaction.atomic():
        set_local_organization(organization_id)
        yield

"""Repository-wide pytest safety hooks."""

import pytest


REVISION_TABLES = (
    "agent_revisions",
    "application_revisions",
    "skill_revisions",
)


def _guard_trigger(table, operation):
    return f"{table}_reject_{operation.lower()}"


def _revision_tables(connection):
    try:
        return set(connection.introspection.table_names()) & set(REVISION_TABLES)
    except Exception:
        return set()


def _install_revision_guards():
    from django.db import connection

    tables = _revision_tables(connection)
    if not tables:
        return
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            for table in tables:
                for operation in ("UPDATE", "DELETE"):
                    trigger = _guard_trigger(table, operation)
                    cursor.execute(
                        f'''CREATE TRIGGER IF NOT EXISTS "{trigger}"
                            BEFORE {operation} ON "{table}"
                            BEGIN
                                SELECT RAISE(ABORT, 'published revisions are immutable');
                            END'''
                    )
        elif connection.vendor == "postgresql":
            for table in tables:
                for operation in ("UPDATE", "DELETE"):
                    trigger = _guard_trigger(table, operation)
                    cursor.execute(
                        "SELECT 1 FROM pg_trigger WHERE tgname = %s",
                        [trigger],
                    )
                    if cursor.fetchone() is None:
                        cursor.execute(
                            f'''CREATE TRIGGER "{trigger}"
                                BEFORE {operation} ON "{table}"
                                FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation()'''
                        )


def _drop_revision_guards():
    from django.db import connection

    tables = _revision_tables(connection)
    if not tables:
        return
    with connection.cursor() as cursor:
        for table in tables:
            for operation in ("update", "delete"):
                trigger = _guard_trigger(table, operation)
                if connection.vendor == "sqlite":
                    cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
                elif connection.vendor == "postgresql":
                    cursor.execute(
                        f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"'
                    )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Restore database immutability before every database-backed test."""

    try:
        _install_revision_guards()
    except Exception:
        # The test database may not have been created yet. Migrations install
        # the initial guards when pytest-django initializes it.
        pass


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    """Let TransactionTestCase flush immutable revision rows safely."""

    try:
        _drop_revision_guards()
    except Exception:
        pass
    yield

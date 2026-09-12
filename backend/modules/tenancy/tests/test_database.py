import pytest
from django.db import connection

from modules.tenancy.database import tenant_database_context


@pytest.mark.django_db(transaction=True)
def test_sqlite_tenant_context_does_not_open_an_atomic_block():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite-specific transaction behavior")

    assert connection.in_atomic_block is False
    with tenant_database_context("00000000-0000-0000-0000-000000000001"):
        assert connection.in_atomic_block is False

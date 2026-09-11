import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from modules.execution.application.runs import create_run
from modules.execution.models import Run
from modules.execution.infrastructure.claim import claim_next_run
from modules.tenancy.models import Membership, Organization


@pytest.mark.django_db(transaction=True)
def test_postgresql_rls_filters_runs_for_non_bypass_role():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-only RLS contract")

    actor = get_user_model().objects.create_user(username="postgres-rls-owner")
    first = Organization.objects.create(name="First", slug="postgres-rls-first", owner=actor)
    second = Organization.objects.create(name="Second", slug="postgres-rls-second", owner=actor)
    Membership.objects.create(organization=first, user=actor, role=Membership.Role.OWNER)
    Membership.objects.create(organization=second, user=actor, role=Membership.Role.OWNER)
    first_run = create_run(
        organization=first,
        owner=actor,
        executor_kind=Run.ExecutorKind.MEDIA,
        source_type="test",
        definition_snapshot={},
        input_data={},
    )
    create_run(
        organization=second,
        owner=actor,
        executor_kind=Run.ExecutorKind.MEDIA,
        source_type="test",
        definition_snapshot={},
        input_data={},
    )
    role = f"rls_test_{uuid.uuid4().hex}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}"')
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT SELECT ON runs TO "{role}"')
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE "{role}"')
                cursor.execute(
                    "SELECT set_config('app.organization_id', %s, true)",
                    [str(first.id)],
                )
                cursor.execute("SELECT id FROM runs ORDER BY id")
                visible_ids = [row[0] for row in cursor.fetchall()]
                cursor.execute("RESET ROLE")
        assert visible_ids == [first_run.id]
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute(f'DROP ROLE IF EXISTS "{role}"')


@pytest.mark.django_db
def test_postgresql_tenant_tables_have_policies():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-only RLS contract")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_policies "
            "WHERE schemaname = current_schema() AND policyname = 'tenant_isolation'"
        )
        policy_tables = {row[0] for row in cursor.fetchall()}
    assert {
        "application_revisions",
        "application_deployments",
        "runs",
        "run_attempts",
        "run_leases",
        "run_events",
    } <= policy_tables


@pytest.mark.django_db(transaction=True)
def test_postgresql_claim_skips_a_run_locked_by_another_transaction():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-only SKIP LOCKED contract")
    actor = get_user_model().objects.create_user(username="postgres-claim-owner")
    organization = Organization.objects.create(
        name="Claim Organization",
        slug="postgres-claim-organization",
        owner=actor,
    )
    Membership.objects.create(
        organization=organization,
        user=actor,
        role=Membership.Role.OWNER,
    )
    first = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.MEDIA,
        source_type="test",
        definition_snapshot={},
        input_data={},
        priority=10,
    )
    second = create_run(
        organization=organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.MEDIA,
        source_type="test",
        definition_snapshot={},
        input_data={},
        priority=0,
    )

    with transaction.atomic():
        Run.objects.select_for_update().get(pk=first.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            claimed = pool.submit(
                claim_next_run,
                worker_id="postgres-worker",
                worker_pool=Run.ExecutorKind.MEDIA,
            ).result(timeout=5)

    assert claimed is not None
    assert claimed.run.id == second.id

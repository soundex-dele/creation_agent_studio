import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction

from modules.execution.application.runs import create_run
from modules.execution.models import Run
from modules.execution.infrastructure.claim import claim_next_run
from apps.enterprise.models import Membership, Organization
from apps.conversations.models import Conversation, Message
from apps.projects.models import Project
from apps.templates.models import Template, TemplateAnalysisSection, TemplateCategory


def _claim_and_close_connections(**kwargs):
    try:
        return claim_next_run(**kwargs)
    finally:
        connections.close_all()


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
            cursor.execute(f'DROP OWNED BY "{role}"')
            cursor.execute(f'DROP ROLE IF EXISTS "{role}"')


@pytest.mark.django_db
def test_postgresql_tenant_tables_have_policies():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-only RLS contract")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT tablename FROM pg_policies "
            "WHERE schemaname = current_schema()"
        )
        policy_tables = {row[0] for row in cursor.fetchall()}
    assert {
        "application_revisions",
        "application_deployments",
        "runs",
        "run_attempts",
        "run_leases",
        "run_events",
        "agents",
        "applications",
        "chat_applications",
        "skills",
        "projects",
        "project_assets",
        "conversations",
        "messages",
        "workflows",
        "workflow_steps",
        "templates",
        "chat_application_revisions",
    } <= policy_tables


@pytest.mark.django_db(transaction=True)
def test_postgresql_product_rls_separates_public_reads_from_tenant_writes():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-only product RLS contract")

    actor = get_user_model().objects.create_user(username="postgres-product-rls")
    first = Organization.objects.create(
        name="Product First", slug="postgres-product-first", owner=actor)
    second = Organization.objects.create(
        name="Product Second", slug="postgres-product-second", owner=actor)
    first_project = Project.objects.create(
        organization=first, user=actor, title="first project")
    Project.objects.create(
        organization=second, user=actor, title="second project")
    first_conversation = Conversation.objects.create(
        organization=first, user=actor, title="first conversation")
    second_conversation = Conversation.objects.create(
        organization=second, user=actor, title="second conversation")
    first_message = Message.objects.create(
        conversation=first_conversation, role="user", content="first message")
    Message.objects.create(
        conversation=second_conversation, role="user", content="second message")
    category = TemplateCategory.objects.create(name="RLS", slug="postgres-rls")
    own_draft = Template.objects.create(
        category=category,
        title="own draft",
        created_by=actor,
        organization=first,
        status="draft",
    )
    foreign_public = Template.objects.create(
        category=category,
        title="foreign public",
        created_by=actor,
        organization=second,
        status="published",
    )
    public_section = TemplateAnalysisSection.objects.create(
        template=foreign_public,
        title="public section",
        content="readable but immutable across tenants",
    )

    role = f"product_rls_test_{uuid.uuid4().hex}"
    tables = (
        "projects", "conversations", "messages", "templates",
        "template_analysis_sections",
    )
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}"')
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT SELECT, UPDATE ON {", ".join(tables)} TO "{role}"')
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE "{role}"')
                cursor.execute(
                    "SELECT set_config('app.organization_id', %s, true)",
                    [str(first.id)],
                )
                cursor.execute("SELECT id FROM projects ORDER BY id")
                assert [row[0] for row in cursor.fetchall()] == [first_project.id]
                cursor.execute("SELECT id FROM messages ORDER BY id")
                assert [row[0] for row in cursor.fetchall()] == [first_message.id]
                cursor.execute("SELECT id FROM templates ORDER BY id")
                assert [row[0] for row in cursor.fetchall()] == [
                    own_draft.id,
                    foreign_public.id,
                ]
                cursor.execute(
                    "SELECT id FROM template_analysis_sections ORDER BY id")
                assert [row[0] for row in cursor.fetchall()] == [public_section.id]
                cursor.execute(
                    "UPDATE templates SET title = 'tampered' WHERE id = %s",
                    [foreign_public.id],
                )
                assert cursor.rowcount == 0
                cursor.execute(
                    "UPDATE template_analysis_sections "
                    "SET content = 'tampered' WHERE id = %s",
                    [public_section.id],
                )
                assert cursor.rowcount == 0
                cursor.execute("RESET ROLE")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute(f'DROP OWNED BY "{role}"')
            cursor.execute(f'DROP ROLE IF EXISTS "{role}"')


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
                _claim_and_close_connections,
                worker_id="postgres-worker",
                worker_pool=Run.ExecutorKind.MEDIA,
            ).result(timeout=5)

    assert claimed is not None
    assert claimed.run.id == second.id

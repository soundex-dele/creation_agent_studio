from django.db import migrations


DIRECT_TABLES = (
    "runs",
    "run_events",
    "run_event_snapshots",
    "run_commands",
    "run_artifacts",
    "idempotency_records",
)

INDIRECT_POLICIES = {
    "run_attempts": (
        "EXISTS (SELECT 1 FROM runs r WHERE r.id = run_id "
        "AND r.organization_id = NULLIF(current_setting("
        "'app.organization_id', true), '')::uuid)"
    ),
    "run_leases": (
        "EXISTS (SELECT 1 FROM run_attempts a JOIN runs r ON r.id = a.run_id "
        "WHERE a.id = attempt_id AND r.organization_id = NULLIF(current_setting("
        "'app.organization_id', true), '')::uuid)"
    ),
}


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in DIRECT_TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )
        for table, expression in INDIRECT_POLICIES.items():
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                f"USING ({expression}) WITH CHECK ({expression})"
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in (*DIRECT_TABLES, *INDIRECT_POLICIES):
            cursor.execute(
                f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"'
            )
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("execution", "0001_initial")]

    operations = [migrations.RunPython(enable_rls, disable_rls)]

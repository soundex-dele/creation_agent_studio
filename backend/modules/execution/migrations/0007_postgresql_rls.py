from django.db import migrations


DIRECT_TABLES = (
    "v2_runs",
    "v2_run_events",
    "v2_run_event_snapshots",
    "v2_run_commands",
    "v2_run_artifacts",
    "v2_idempotency_records",
)

INDIRECT_POLICIES = {
    "v2_run_attempts": (
        "EXISTS (SELECT 1 FROM v2_runs r WHERE r.id = run_id "
        "AND r.organization_id = NULLIF(current_setting("
        "'app.organization_id', true), '')::uuid)"
    ),
    "v2_run_leases": (
        "EXISTS (SELECT 1 FROM v2_run_attempts a JOIN v2_runs r ON r.id = a.run_id "
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
                f'CREATE POLICY "v2_tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )
        for table, expression in INDIRECT_POLICIES.items():
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "v2_tenant_isolation" ON "{table}" '
                f"USING ({expression}) WITH CHECK ({expression})"
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in (*DIRECT_TABLES, *INDIRECT_POLICIES):
            cursor.execute(
                f'DROP POLICY IF EXISTS "v2_tenant_isolation" ON "{table}"'
            )
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("v2_execution", "0006_runeventsnapshot"),
        ("v2_tenancy", "0002_postgresql_rls"),
    ]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

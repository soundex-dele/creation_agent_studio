from django.db import migrations


DIRECT_POLICIES = {
    "v2_organizations": "id",
    "v2_organization_memberships": "organization_id",
}


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, column in DIRECT_POLICIES.items():
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "v2_tenant_isolation" ON "{table}" '
                f'USING ("{column}" = NULLIF(current_setting('
                "'app.organization_id', true), '')::uuid) "
                f'WITH CHECK ("{column}" = NULLIF(current_setting('
                "'app.organization_id', true), '')::uuid)"
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in DIRECT_POLICIES:
            cursor.execute(
                f'DROP POLICY IF EXISTS "v2_tenant_isolation" ON "{table}"'
            )
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("v2_tenancy", "0001_initial")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

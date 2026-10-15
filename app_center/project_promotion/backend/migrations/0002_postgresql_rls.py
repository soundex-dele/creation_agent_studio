from django.db import migrations

TABLES = ('case', 'topic', 'channel', 'version', 'feedback', 'aitask', 'workspace', 'handoff')


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for name in TABLES:
            table = f'project_promotion_{name}'
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)")


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for name in TABLES:
            table = f'project_promotion_{name}'
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [('project_promotion', '0001_initial')]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

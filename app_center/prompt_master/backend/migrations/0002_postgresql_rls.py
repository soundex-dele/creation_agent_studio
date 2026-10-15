from django.db import migrations

TABLES = ("prompt_master_session", "prompt_master_version", "prompt_master_task")


def enable(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
                cursor.execute(f"CREATE POLICY tenant_isolation ON {table} "
                               "USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
                               "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)")


def disable(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
                cursor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("prompt_master", "0001_initial")]
    operations = [migrations.RunPython(enable, disable)]

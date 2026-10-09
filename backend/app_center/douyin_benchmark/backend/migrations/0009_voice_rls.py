from django.db import migrations


TABLES = ['douyin_benchmark_voicesample', 'douyin_benchmark_voiceversion']


def enable(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    predicate = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(f'CREATE POLICY tenant_isolation ON "{table}" USING ({predicate}) WITH CHECK ({predicate})')


def disable(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [('douyin_benchmark', '0008_creatorprofile_account_and_more')]
    operations = [migrations.RunPython(enable, disable)]

from django.db import migrations

POLICIES = {
    "douyin_benchmark_account": "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid",
    "douyin_benchmark_work": "account_id IN (SELECT id FROM douyin_benchmark_account)",
    "douyin_benchmark_task": "account_id IN (SELECT id FROM douyin_benchmark_account)",
    "douyin_benchmark_snapshot": "batch_id IN (SELECT id FROM douyin_benchmark_task) AND work_id IN (SELECT id FROM douyin_benchmark_work)",
    "douyin_benchmark_scriptversion": "task_id IN (SELECT id FROM douyin_benchmark_task)",
}


def enable(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            for table, predicate in POLICIES.items():
                cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
                cursor.execute(f'CREATE POLICY tenant_isolation ON "{table}" USING ({predicate}) WITH CHECK ({predicate})')


def disable(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            for table in reversed(POLICIES):
                cursor.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
                cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("douyin_benchmark", "0001_initial")]
    operations = [migrations.RunPython(enable, disable)]

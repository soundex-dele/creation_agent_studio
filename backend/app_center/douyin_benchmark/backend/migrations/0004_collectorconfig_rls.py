from django.db import migrations


def enable(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute('ALTER TABLE douyin_benchmark_collectorconfig ENABLE ROW LEVEL SECURITY')
        schema_editor.execute('ALTER TABLE douyin_benchmark_collectorconfig FORCE ROW LEVEL SECURITY')
        schema_editor.execute("CREATE POLICY tenant_isolation ON douyin_benchmark_collectorconfig USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)")


def disable(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute('DROP POLICY IF EXISTS tenant_isolation ON douyin_benchmark_collectorconfig')
        schema_editor.execute('ALTER TABLE douyin_benchmark_collectorconfig DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("douyin_benchmark", "0003_collectorconfig")]
    operations = [migrations.RunPython(enable, disable)]

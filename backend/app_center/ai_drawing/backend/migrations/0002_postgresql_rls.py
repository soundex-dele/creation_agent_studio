from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute('ALTER TABLE "ai_drawing_references" ENABLE ROW LEVEL SECURITY')
    schema_editor.execute('ALTER TABLE "ai_drawing_references" FORCE ROW LEVEL SECURITY')
    schema_editor.execute(
        'CREATE POLICY "tenant_isolation" ON "ai_drawing_references" '
        "USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
        "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)"
    )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute('DROP POLICY IF EXISTS "tenant_isolation" ON "ai_drawing_references"')
        schema_editor.execute('ALTER TABLE "ai_drawing_references" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("ai_drawing", "0001_initial")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

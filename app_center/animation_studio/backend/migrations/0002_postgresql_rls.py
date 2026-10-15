from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute('ALTER TABLE "animation_studio_assets" ENABLE ROW LEVEL SECURITY')
        schema_editor.execute('ALTER TABLE "animation_studio_assets" FORCE ROW LEVEL SECURITY')
        schema_editor.execute(
            'CREATE POLICY "tenant_isolation" ON "animation_studio_assets" '
            "USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute('DROP POLICY IF EXISTS "tenant_isolation" ON "animation_studio_assets"')
        schema_editor.execute('ALTER TABLE "animation_studio_assets" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("animation_studio", "0001_initial")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

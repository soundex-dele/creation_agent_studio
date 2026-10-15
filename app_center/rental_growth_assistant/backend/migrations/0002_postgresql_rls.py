from django.db import migrations


TABLES = ('rental_growth_content', 'rental_growth_contentversion', 'rental_growth_lead', 'rental_growth_followup', 'rental_growth_persona', 'rental_growth_preferences', 'rental_growth_property', 'rental_growth_publication', 'rental_growth_metricobservation', 'rental_growth_viewing', 'rental_growth_aitask')


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("rental_growth", "0001_initial")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

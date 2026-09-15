from django.db import migrations


DIRECT_TABLES = ("address_books", "contacts")
METHOD_POLICY = (
    "EXISTS (SELECT 1 FROM contacts c WHERE c.id = contact_id "
    "AND c.organization_id = NULLIF(current_setting("
    "'app.organization_id', true), '')::uuid)"
)


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in DIRECT_TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )
        cursor.execute('ALTER TABLE "contact_methods" ENABLE ROW LEVEL SECURITY')
        cursor.execute('ALTER TABLE "contact_methods" FORCE ROW LEVEL SECURITY')
        cursor.execute(
            'CREATE POLICY "tenant_isolation" ON "contact_methods" '
            f"USING ({METHOD_POLICY}) WITH CHECK ({METHOD_POLICY})"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in (*DIRECT_TABLES, "contact_methods"):
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("contacts", "0001_initial")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

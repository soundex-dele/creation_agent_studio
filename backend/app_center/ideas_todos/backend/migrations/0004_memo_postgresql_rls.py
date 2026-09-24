from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE "ideas_todos_memos" ENABLE ROW LEVEL SECURITY')
        cursor.execute('ALTER TABLE "ideas_todos_memos" FORCE ROW LEVEL SECURITY')
        cursor.execute(
            'CREATE POLICY "tenant_isolation" ON "ideas_todos_memos" '
            "USING (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid)"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP POLICY IF EXISTS "tenant_isolation" ON "ideas_todos_memos"')
        cursor.execute('ALTER TABLE "ideas_todos_memos" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("ideas_todos", "0003_memo")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

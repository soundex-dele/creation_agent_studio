from django.db import migrations


TENANT_TABLES = (
    "creation_toolbox_workspaces",
    "creation_toolbox_projects",
    "creation_toolbox_folders",
    "creation_toolbox_assets",
    "creation_toolbox_recordings",
    "creation_toolbox_copywritings",
    "creation_toolbox_scripts",
)
SCENE_POLICY = (
    "EXISTS (SELECT 1 FROM creation_toolbox_scripts s WHERE s.id = script_id "
    "AND s.organization_id = NULLIF(current_setting("
    "'app.organization_id', true), '')::uuid)"
)


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )
        cursor.execute('ALTER TABLE "creation_toolbox_scenes" ENABLE ROW LEVEL SECURITY')
        cursor.execute('ALTER TABLE "creation_toolbox_scenes" FORCE ROW LEVEL SECURITY')
        cursor.execute(
            'CREATE POLICY "tenant_isolation" ON "creation_toolbox_scenes" '
            f"USING ({SCENE_POLICY}) WITH CHECK ({SCENE_POLICY})"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in (*TENANT_TABLES, "creation_toolbox_scenes"):
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("creation_toolbox", "0001_initial")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]


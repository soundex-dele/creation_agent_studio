from django.db import migrations


TABLES = (
    "v2_agents",
    "v2_agent_drafts",
    "v2_agent_revisions",
    "v2_agent_deployments",
    "v2_skills",
    "v2_skill_drafts",
    "v2_skill_revisions",
    "v2_applications",
    "v2_application_drafts",
    "v2_application_revisions",
    "v2_application_deployments",
)


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "v2_tenant_isolation" ON "{table}" '
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
            cursor.execute(
                f'DROP POLICY IF EXISTS "v2_tenant_isolation" ON "{table}"'
            )
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("v2_catalog", "0003_revision_delete_guards"),
        ("v2_tenancy", "0002_postgresql_rls"),
    ]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

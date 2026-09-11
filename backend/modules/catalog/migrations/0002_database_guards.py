from django.db import migrations


REVISION_TABLES = (
    "agent_revisions",
    "application_revisions",
    "skill_revisions",
)

TENANT_TABLES = (
    "agent_drafts",
    "agent_revisions",
    "agent_deployments",
    "skill_drafts",
    "skill_revisions",
    "application_drafts",
    "application_revisions",
    "application_deployments",
)


def install_guards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for table in REVISION_TABLES:
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"{table}_reject_{operation.lower()}"
                    cursor.execute(
                        f'''
                        CREATE TRIGGER "{trigger}"
                        BEFORE {operation} ON "{table}"
                        BEGIN
                            SELECT RAISE(ABORT, 'published revisions are immutable');
                        END
                        '''
                    )
        elif vendor == "postgresql":
            cursor.execute(
                '''
                CREATE OR REPLACE FUNCTION reject_revision_mutation()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'published revisions are immutable';
                END;
                $$ LANGUAGE plpgsql
                '''
            )
            for table in REVISION_TABLES:
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"{table}_reject_{operation.lower()}"
                    cursor.execute(
                        f'''
                        CREATE TRIGGER "{trigger}"
                        BEFORE {operation} ON "{table}"
                        FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation()
                        '''
                    )
            for table in TENANT_TABLES:
                cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
                cursor.execute(
                    f'CREATE POLICY "tenant_isolation" ON "{table}" '
                    "USING (organization_id = NULLIF(current_setting("
                    "'app.organization_id', true), '')::uuid) "
                    "WITH CHECK (organization_id = NULLIF(current_setting("
                    "'app.organization_id', true), '')::uuid)"
                )


def remove_guards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        for table in REVISION_TABLES:
            for operation in ("update", "delete"):
                trigger = f"{table}_reject_{operation}"
                if vendor == "sqlite":
                    cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
                elif vendor == "postgresql":
                    cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"')
        if vendor == "postgresql":
            cursor.execute("DROP FUNCTION IF EXISTS reject_revision_mutation()")
            for table in TENANT_TABLES:
                cursor.execute(
                    f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"'
                )
                cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.RunPython(install_guards, reverse_code=remove_guards),
    ]

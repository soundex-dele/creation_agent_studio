from django.db import migrations


REVISION_TABLES = (
    "v2_agent_revisions",
    "v2_application_revisions",
    "v2_skill_revisions",
)


def create_revision_update_guards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for table in REVISION_TABLES:
                trigger = f"{table}_reject_update"
                cursor.execute(
                    f'''
                    CREATE TRIGGER "{trigger}"
                    BEFORE UPDATE ON "{table}"
                    BEGIN
                        SELECT RAISE(ABORT, 'published revisions are immutable');
                    END
                    '''
                )
        elif vendor == "postgresql":
            cursor.execute(
                '''
                CREATE OR REPLACE FUNCTION v2_reject_revision_update()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'published revisions are immutable';
                END;
                $$ LANGUAGE plpgsql
                '''
            )
            for table in REVISION_TABLES:
                trigger = f"{table}_reject_update"
                cursor.execute(
                    f'''
                    CREATE TRIGGER "{trigger}"
                    BEFORE UPDATE ON "{table}"
                    FOR EACH ROW EXECUTE FUNCTION v2_reject_revision_update()
                    '''
                )


def drop_revision_update_guards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        for table in REVISION_TABLES:
            trigger = f"{table}_reject_update"
            if vendor == "sqlite":
                cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
            elif vendor == "postgresql":
                cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"')
        if vendor == "postgresql":
            cursor.execute("DROP FUNCTION IF EXISTS v2_reject_revision_update()")


class Migration(migrations.Migration):
    dependencies = [("v2_catalog", "0001_initial")]

    operations = [
        migrations.RunPython(
            create_revision_update_guards,
            reverse_code=drop_revision_update_guards,
        )
    ]

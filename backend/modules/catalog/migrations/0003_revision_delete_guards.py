from django.db import migrations


REVISION_TABLES = (
    "v2_agent_revisions",
    "v2_application_revisions",
    "v2_skill_revisions",
)


def create_revision_delete_guards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for table in REVISION_TABLES:
                trigger = f"{table}_reject_delete"
                cursor.execute(
                    f'''
                    CREATE TRIGGER "{trigger}"
                    BEFORE DELETE ON "{table}"
                    BEGIN
                        SELECT RAISE(ABORT, 'published revisions are immutable');
                    END
                    '''
                )
        elif vendor == "postgresql":
            for table in REVISION_TABLES:
                trigger = f"{table}_reject_delete"
                cursor.execute(
                    f'''
                    CREATE TRIGGER "{trigger}"
                    BEFORE DELETE ON "{table}"
                    FOR EACH ROW EXECUTE FUNCTION v2_reject_revision_update()
                    '''
                )


def drop_revision_delete_guards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        for table in REVISION_TABLES:
            trigger = f"{table}_reject_delete"
            if vendor == "sqlite":
                cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
            elif vendor == "postgresql":
                cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"')


class Migration(migrations.Migration):
    dependencies = [("v2_catalog", "0002_revision_update_guards")]

    operations = [
        migrations.RunPython(
            create_revision_delete_guards,
            reverse_code=drop_revision_delete_guards,
        )
    ]

from django.db import migrations


def retire_newmedia_workbench(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    Application.objects.using(schema_editor.connection.alias).filter(
        slug="newmedia-workbench",
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0008_application_access_scope_application_allowed_users"),
    ]

    operations = [
        migrations.RunPython(retire_newmedia_workbench, migrations.RunPython.noop),
    ]

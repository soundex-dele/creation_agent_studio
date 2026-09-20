from django.db import migrations


def retire_contacts(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    Application.objects.using(schema_editor.connection.alias).filter(
        slug="contacts",
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0010_retire_batch_transcribe"),
    ]

    operations = [
        migrations.RunPython(retire_contacts, migrations.RunPython.noop),
    ]

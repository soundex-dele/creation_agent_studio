from django.db import migrations


def retire_batch_transcribe(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    Application.objects.using(schema_editor.connection.alias).filter(
        slug="batch-transcribe",
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0009_retire_newmedia_workbench"),
    ]

    operations = [
        migrations.RunPython(retire_batch_transcribe, migrations.RunPython.noop),
    ]

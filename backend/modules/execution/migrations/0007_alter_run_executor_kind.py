from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("execution", "0006_supervisor_commands"),
    ]

    operations = [
        migrations.AlterField(
            model_name="run",
            name="executor_kind",
            field=models.CharField(
                choices=[
                    ("agent", "Agent"),
                    ("media", "Media"),
                    ("workflow", "Workflow"),
                    ("evaluation", "Evaluation"),
                    ("knowledge", "Knowledge"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]

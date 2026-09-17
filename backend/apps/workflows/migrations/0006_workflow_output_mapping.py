from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0005_workflow_execution_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflow",
            name="output_mapping",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

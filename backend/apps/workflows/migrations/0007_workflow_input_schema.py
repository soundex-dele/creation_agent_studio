from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0006_workflow_output_mapping"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflow",
            name="input_schema",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="workflowstep",
            name="input_mapping",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

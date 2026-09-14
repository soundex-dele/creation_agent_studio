import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("enterprise", "0005_external_identity"),
        ("execution", "0005_run_queue_entry"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationrun",
            name="execution_run",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="evaluation_record",
                to="execution.run",
            ),
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("v2_execution", "0001_initial")]

    operations = [
        migrations.RemoveField(
            model_name="runattempt",
            name="checkpoint_object_key",
        ),
        migrations.AddField(
            model_name="run",
            name="pending_input_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="pending_input_kind",
            field=models.CharField(
                blank=True,
                choices=[("answer", "Answer"), ("permission", "Permission")],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="run",
            name="pending_input_request_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runattempt",
            name="checkpoint_artifact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="v2_execution.runartifact",
            ),
        ),
    ]

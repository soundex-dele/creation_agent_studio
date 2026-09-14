from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("execution", "0003_run_hierarchy")]

    operations = [
        migrations.AlterField(
            model_name="run",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("waiting_input", "Waiting for input"),
                    ("waiting_children", "Waiting for child runs"),
                    ("cancelling", "Cancelling"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                db_index=True,
                default="queued",
                max_length=20,
            ),
        ),
    ]

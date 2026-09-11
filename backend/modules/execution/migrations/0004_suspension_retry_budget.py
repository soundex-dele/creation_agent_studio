from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("v2_execution", "0003_run_executor_key")]

    operations = [
        migrations.RemoveConstraint(
            model_name="run",
            name="v2_run_attempts_within_limit",
        )
    ]

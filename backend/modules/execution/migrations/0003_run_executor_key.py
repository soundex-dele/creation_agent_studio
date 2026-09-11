from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("v2_execution", "0002_interactive_checkpoint")]

    operations = [
        migrations.AddField(
            model_name="run",
            name="executor_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=100),
        )
    ]

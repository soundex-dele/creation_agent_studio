import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("automations", "0001_initial"),
        ("enterprise", "0007_move_automation_trigger_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="automation",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="automation_triggers",
                to="enterprise.organization",
            ),
        )
    ]

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("enterprise", "0006_evaluation_run_execution"),
        ("automations", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="AutomationTrigger")],
            database_operations=[],
        )
    ]

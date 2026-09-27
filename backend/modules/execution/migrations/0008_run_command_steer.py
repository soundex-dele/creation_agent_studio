from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("execution", "0007_alter_run_executor_kind")]
    operations = [migrations.AlterField(
        model_name="runcommand", name="type",
        field=models.CharField(max_length=30, choices=[
            ("steer", "Steer active turn"), ("answer", "Answer"),
            ("grant_permission", "Grant permission"), ("deny_permission", "Deny permission"),
            ("approve_plan", "Approve plan"), ("revise_plan", "Revise plan"), ("cancel", "Cancel"),
        ]),
    )]

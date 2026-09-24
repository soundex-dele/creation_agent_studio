from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("remote_access", "0002_alter_localremoteconfig_computer_name")]
    operations = [migrations.AddField(
        model_name="localremoteconfig", name="terminal_enabled",
        field=models.BooleanField(default=False),
    )]

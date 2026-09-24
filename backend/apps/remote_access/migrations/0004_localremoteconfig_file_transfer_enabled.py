from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('remote_access', '0003_localremoteconfig_terminal_enabled')]
    operations = [migrations.AddField(
        model_name='localremoteconfig', name='file_transfer_enabled',
        field=models.BooleanField(default=False),
    )]

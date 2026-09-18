from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conversations", "0012_messageattachment")]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="agent_locked",
            field=models.BooleanField(default=False),
        ),
    ]

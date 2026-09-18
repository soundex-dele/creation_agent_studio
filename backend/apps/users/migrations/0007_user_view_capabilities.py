from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_refine_account_capabilities'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='can_view_agents',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='can_view_applications',
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_user_can_create_agents_user_can_create_applications_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='user',
            old_name='can_manage_agents',
            new_name='can_update_agents',
        ),
        migrations.RenameField(
            model_name='user',
            old_name='can_manage_applications',
            new_name='can_toggle_applications',
        ),
        migrations.RemoveField(
            model_name='user',
            name='can_create_applications',
        ),
        migrations.AddField(
            model_name='user',
            name='can_delete_agents',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='can_toggle_agents',
            field=models.BooleanField(default=False),
        ),
    ]

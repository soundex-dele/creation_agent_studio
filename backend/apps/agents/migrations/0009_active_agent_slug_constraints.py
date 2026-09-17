from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('agents', '0008_publish_initial_agent_versions'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='agent',
            name='unique_agent_slug_per_org',
        ),
        migrations.RemoveConstraint(
            model_name='agent',
            name='unique_global_agent_slug',
        ),
        migrations.AddConstraint(
            model_name='agent',
            constraint=models.UniqueConstraint(
                condition=models.Q(is_active=True),
                fields=('organization', 'slug'),
                name='unique_agent_slug_per_org',
            ),
        ),
        migrations.AddConstraint(
            model_name='agent',
            constraint=models.UniqueConstraint(
                condition=models.Q(is_active=True, organization__isnull=True),
                fields=('slug',),
                name='unique_global_agent_slug',
            ),
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('conversations', '0008_conversation_agent_thread'),
        ('execution', '0002_postgresql_rls'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='run',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='projected_messages',
                to='execution.run',
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='run_event_sequence',
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='message',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    run__isnull=False,
                    run_event_sequence__isnull=False,
                ),
                fields=('run', 'run_event_sequence'),
                name='unique_run_event_message',
            ),
        ),
    ]

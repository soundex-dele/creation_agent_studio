from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('conversations', '0007_chat_application_context'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='agent_thread_provider',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='conversation',
            name='agent_thread_id',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddConstraint(
            model_name='conversation',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(agent_thread_provider='', agent_thread_id='')
                    | (
                        ~models.Q(agent_thread_provider='')
                        & ~models.Q(agent_thread_id='')
                    )
                ),
                name='conversation_agent_thread_consistent',
            ),
        ),
    ]

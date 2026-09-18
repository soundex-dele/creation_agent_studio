from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('agents', '0006_move_agent_definition_to_catalog')]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='kind',
            field=models.CharField(
                choices=[('standard', '标准智能体'), ('supervisor', 'AI 分身')],
                db_index=True,
                default='standard',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='SupervisorProfile',
            fields=[
                (
                    'agent',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name='supervisor_profile',
                        serialize=False,
                        to='agents.agent',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'supervisor_profiles'},
        ),
    ]

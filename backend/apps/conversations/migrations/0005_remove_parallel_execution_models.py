from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0004_agentthread_agentturn_agentserverrequest_agentitem_and_more"),
    ]

    operations = [
        migrations.DeleteModel(name="AgentServerRequest"),
        migrations.DeleteModel(name="AgentItem"),
        migrations.DeleteModel(name="AgentTurn"),
        migrations.DeleteModel(name="AgentThread"),
        migrations.RemoveField(model_name="conversation", name="workflow_step_run"),
    ]

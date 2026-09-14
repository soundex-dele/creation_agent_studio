from django.db import migrations


def clear_implicit_general_agent(apps, schema_editor):
    """General is now an execution fallback instead of a saved selection."""

    Agent = apps.get_model("agents", "Agent")
    Conversation = apps.get_model("conversations", "Conversation")
    general_ids = Agent.objects.filter(slug="general").values_list("id", flat=True)
    Conversation.objects.filter(agent_id__in=general_ids).update(agent_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0009_message_run_events"),
    ]

    operations = [
        migrations.RunPython(
            clear_implicit_general_agent,
            migrations.RunPython.noop,
        ),
    ]

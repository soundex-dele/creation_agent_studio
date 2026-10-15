from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0013_conversation_agent_locked"),
        ("study_with_method", "0008_multi_subject_profiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="source_attachment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="study_problems",
                to="conversations.messageattachment",
            ),
        ),
    ]

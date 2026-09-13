import django.db.models.deletion
from django.db import migrations, models


def remove_unscoped_conversations(apps, schema_editor):
    Conversation = apps.get_model("conversations", "Conversation")
    Conversation.objects.filter(organization__isnull=True).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0005_remove_parallel_execution_models"),
        ("execution", "0002_postgresql_rls"),
    ]

    operations = [
        migrations.RunPython(
            remove_unscoped_conversations,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="conversation",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="conversations",
                to="enterprise.organization",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="run",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projected_message",
                to="execution.run",
            ),
        ),
    ]

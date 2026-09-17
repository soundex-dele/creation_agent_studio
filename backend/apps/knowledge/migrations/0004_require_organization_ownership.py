import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("enterprise", "0008_remove_knowledgedocument_knowledge_base_and_more"),
        ("knowledge", "0003_native_indexes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="knowledgedocument",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="knowledge_documents",
                to="enterprise.organization",
            ),
        ),
        migrations.AlterField(
            model_name="knowledgechunk",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="knowledge_chunks",
                to="enterprise.organization",
            ),
        ),
    ]

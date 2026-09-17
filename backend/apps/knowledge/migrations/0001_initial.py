import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("enterprise", "0008_remove_knowledgedocument_knowledge_base_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="KnowledgeBase",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("name", models.CharField(max_length=160)),
                        ("description", models.TextField(blank=True)),
                        ("embedding_provider", models.CharField(blank=True, max_length=100)),
                        ("embedding_model", models.CharField(blank=True, max_length=160)),
                        ("chunk_size", models.PositiveIntegerField(default=800)),
                        ("chunk_overlap", models.PositiveIntegerField(default=100)),
                        ("access_policy", models.JSONField(blank=True, default=dict)),
                        ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="knowledge_bases", to="enterprise.organization")),
                    ],
                    options={"db_table": "knowledge_bases"},
                ),
                migrations.CreateModel(
                    name="KnowledgeDocument",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("title", models.CharField(max_length=300)),
                        ("source_type", models.CharField(default="text", max_length=30)),
                        ("source_uri", models.CharField(blank=True, max_length=1000)),
                        ("content", models.TextField(blank=True)),
                        ("checksum", models.CharField(blank=True, db_index=True, max_length=64)),
                        ("status", models.CharField(choices=[("pending", "Pending"), ("indexing", "Indexing"), ("ready", "Ready"), ("failed", "Failed")], default="pending", max_length=20)),
                        ("metadata", models.JSONField(blank=True, default=dict)),
                        ("error", models.TextField(blank=True)),
                        ("knowledge_base", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="knowledge.knowledgebase")),
                    ],
                    options={"db_table": "knowledge_documents"},
                ),
                migrations.CreateModel(
                    name="KnowledgeChunk",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("position", models.PositiveIntegerField()),
                        ("content", models.TextField()),
                        ("token_count", models.PositiveIntegerField(default=0)),
                        ("embedding", models.JSONField(blank=True, default=list)),
                        ("metadata", models.JSONField(blank=True, default=dict)),
                        ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="knowledge.knowledgedocument")),
                    ],
                    options={"db_table": "knowledge_chunks", "ordering": ["position"]},
                ),
                migrations.AddConstraint(
                    model_name="knowledgebase",
                    constraint=models.UniqueConstraint(fields=("organization", "name"), name="unique_org_knowledge_base"),
                ),
                migrations.AddConstraint(
                    model_name="knowledgechunk",
                    constraint=models.UniqueConstraint(fields=("document", "position"), name="unique_document_chunk_position"),
                ),
            ],
        ),
    ]

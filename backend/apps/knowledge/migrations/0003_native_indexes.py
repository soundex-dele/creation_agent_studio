from django.db import migrations


def backfill_ownership(apps, schema_editor):
    KnowledgeDocument = apps.get_model("knowledge", "KnowledgeDocument")
    KnowledgeChunk = apps.get_model("knowledge", "KnowledgeChunk")
    from apps.knowledge.retrieval import lexical_text
    for document in KnowledgeDocument.objects.select_related("knowledge_base").all():
        updates = {}
        if document.organization_id is None:
            updates["organization_id"] = document.knowledge_base.organization_id
        if document.status == "ready" and document.active_revision == 0:
            updates["active_revision"] = 1
        if updates:
            KnowledgeDocument.objects.filter(pk=document.pk).update(**updates)
        KnowledgeChunk.objects.filter(document_id=document.id).update(
            organization_id=document.knowledge_base.organization_id,
            revision=max(1, updates.get("active_revision", document.active_revision)),
        )
    for chunk in KnowledgeChunk.objects.filter(lexical_text="").iterator():
        KnowledgeChunk.objects.filter(pk=chunk.pk).update(
            lexical_text=lexical_text(chunk.content))


def create_indexes(apps, schema_editor):
    from apps.knowledge.index_backend import ensure_native_indexes, replace_document_index
    from apps.knowledge.models import KnowledgeDocument
    ensure_native_indexes(schema_editor)
    for document in KnowledgeDocument.objects.filter(
            status="ready", is_deleted=False, active_revision__gt=0).iterator():
        replace_document_index(
            document,
            list(document.chunks.filter(revision=document.active_revision)),
        )
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            for table in (
                "knowledge_bases", "knowledge_documents", "knowledge_chunks",
                "knowledge_vector_index", "knowledge_lexical_index",
            ):
                cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
                cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
                cursor.execute(
                    f'CREATE POLICY "tenant_isolation" ON "{table}" '
                    "USING (organization_id = NULLIF(current_setting("
                    "'app.organization_id', true), '')::uuid) "
                    "WITH CHECK (organization_id = NULLIF(current_setting("
                    "'app.organization_id', true), '')::uuid)"
                )


def drop_indexes(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            for table in ("knowledge_bases", "knowledge_documents", "knowledge_chunks"):
                cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
                cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        cursor.execute("DROP TABLE IF EXISTS knowledge_vector_index")
        cursor.execute("DROP TABLE IF EXISTS knowledge_lexical_index")


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0002_alter_knowledgedocument_options_and_more")]
    operations = [
        migrations.RunPython(backfill_ownership, migrations.RunPython.noop),
        migrations.RunPython(create_indexes, drop_indexes),
    ]

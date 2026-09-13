from django.db import migrations


DIRECT_POLICIES = {
    "agents": (
        "organization_id = cas_tenant_id() OR "
        "(organization_id IS NULL AND is_public = TRUE)"
    ),
    "applications": (
        "organization_id = cas_tenant_id() OR "
        "(organization_id IS NULL AND is_public = TRUE)"
    ),
    "skills": (
        "organization_id = cas_tenant_id() OR "
        "(organization_id IS NULL AND visibility = 'public')"
    ),
    "projects": "organization_id = cas_tenant_id()",
    "conversations": "organization_id = cas_tenant_id()",
    "workflows": "organization_id = cas_tenant_id()",
    "templates": (
        "organization_id = cas_tenant_id() OR status = 'published'"
    ),
}

DIRECT_WRITES = {
    table: "organization_id = cas_tenant_id()"
    for table in DIRECT_POLICIES
}

INDIRECT_POLICIES = {
    "chat_applications": (
        "EXISTS (SELECT 1 FROM applications a WHERE a.id = application_id "
        "AND (a.organization_id = cas_tenant_id() OR "
        "(a.organization_id IS NULL AND a.is_public = TRUE)))"
    ),
    "chat_application_revisions": (
        "EXISTS (SELECT 1 FROM application_revisions r WHERE r.id = revision_id "
        "AND r.organization_id = cas_tenant_id())"
    ),
    "project_assets": (
        "EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id "
        "AND p.organization_id = cas_tenant_id())"
    ),
    "conversation_skill_bindings": (
        "EXISTS (SELECT 1 FROM conversations c WHERE c.id = conversation_id "
        "AND c.organization_id = cas_tenant_id())"
    ),
    "messages": (
        "EXISTS (SELECT 1 FROM conversations c WHERE c.id = conversation_id "
        "AND c.organization_id = cas_tenant_id())"
    ),
    "workflow_steps": (
        "EXISTS (SELECT 1 FROM workflows w WHERE w.id = workflow_id "
        "AND w.organization_id = cas_tenant_id())"
    ),
    "template_analysis_sections": (
        "EXISTS (SELECT 1 FROM templates t WHERE t.id = template_id "
        "AND (t.organization_id = cas_tenant_id() OR t.status = 'published'))"
    ),
}

INDIRECT_WRITES = {
    "chat_applications": (
        "EXISTS (SELECT 1 FROM applications a WHERE a.id = application_id "
        "AND a.organization_id = cas_tenant_id())"
    ),
    "chat_application_revisions": (
        "EXISTS (SELECT 1 FROM application_revisions r WHERE r.id = revision_id "
        "AND r.organization_id = cas_tenant_id())"
    ),
    "project_assets": (
        "EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id "
        "AND p.organization_id = cas_tenant_id())"
    ),
    "conversation_skill_bindings": (
        "EXISTS (SELECT 1 FROM conversations c WHERE c.id = conversation_id "
        "AND c.organization_id = cas_tenant_id())"
    ),
    "messages": (
        "EXISTS (SELECT 1 FROM conversations c WHERE c.id = conversation_id "
        "AND c.organization_id = cas_tenant_id())"
    ),
    "workflow_steps": (
        "EXISTS (SELECT 1 FROM workflows w WHERE w.id = workflow_id "
        "AND w.organization_id = cas_tenant_id())"
    ),
    "template_analysis_sections": (
        "EXISTS (SELECT 1 FROM templates t WHERE t.id = template_id "
        "AND t.organization_id = cas_tenant_id())"
    ),
}


def _create_policies(cursor, table, read_expression, write_expression):
    cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    cursor.execute(
        f'CREATE POLICY "tenant_read" ON "{table}" FOR SELECT '
        f"USING ({read_expression})"
    )
    cursor.execute(
        f'CREATE POLICY "tenant_insert" ON "{table}" FOR INSERT '
        f"WITH CHECK ({write_expression})"
    )
    cursor.execute(
        f'CREATE POLICY "tenant_update" ON "{table}" FOR UPDATE '
        f"USING ({write_expression}) WITH CHECK ({write_expression})"
    )
    cursor.execute(
        f'CREATE POLICY "tenant_delete" ON "{table}" FOR DELETE '
        f"USING ({write_expression})"
    )


def enable_product_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION cas_tenant_id() RETURNS uuid AS $$
                SELECT NULLIF(current_setting('app.organization_id', true), '')::uuid
            $$ LANGUAGE SQL STABLE
            """
        )
        for table, expression in DIRECT_POLICIES.items():
            _create_policies(cursor, table, expression, DIRECT_WRITES[table])
        for table, expression in INDIRECT_POLICIES.items():
            _create_policies(cursor, table, expression, INDIRECT_WRITES[table])


def disable_product_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in (*DIRECT_POLICIES, *INDIRECT_POLICIES):
            for policy in (
                "tenant_read", "tenant_insert", "tenant_update", "tenant_delete"
            ):
                cursor.execute(
                    f'DROP POLICY IF EXISTS "{policy}" ON "{table}"'
                )
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        cursor.execute("DROP FUNCTION IF EXISTS cas_tenant_id()")


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0006_move_agent_definition_to_catalog"),
        ("applications", "0006_chat_application_subtype"),
        ("catalog", "0004_deploy_seeded_general_agent"),
        ("conversations", "0007_chat_application_context"),
        ("projects", "0009_require_project_organization"),
        ("templates", "0003_alter_template_options_remove_template_description_and_more"),
        ("workflows", "0004_workflow_dag"),
    ]

    operations = [
        migrations.RunPython(enable_product_rls, disable_product_rls),
    ]

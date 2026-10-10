from django.db import migrations

TABLES = ('project', 'snapshot', 'task', 'content', 'version', 'handoff')


def enable(apps, editor):
    if editor.connection.vendor != 'postgresql':
        return
    for name in TABLES:
        table = 'repo_explainer_' + name
        if name == 'project':
            clause = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
        elif name == 'version':
            clause = f'EXISTS (SELECT 1 FROM repo_explainer_content c JOIN repo_explainer_project p ON p.id = c.project_id WHERE c.id = "{table}".content_id)'
        else:
            clause = f'EXISTS (SELECT 1 FROM repo_explainer_project p WHERE p.id = "{table}".project_id)'
        editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        editor.execute(f'CREATE POLICY tenant_isolation ON "{table}" USING ({clause}) WITH CHECK ({clause})')


def disable(apps, editor):
    if editor.connection.vendor == 'postgresql':
        for name in reversed(TABLES):
            editor.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "repo_explainer_{name}"')
            editor.execute(f'ALTER TABLE "repo_explainer_{name}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [('repo_explainer', '0001_initial')]
    operations = [migrations.RunPython(enable, disable)]

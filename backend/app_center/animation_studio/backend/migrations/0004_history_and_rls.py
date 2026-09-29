from django.db import migrations

TABLES = ["animation_studio_projects", "animation_studio_versions", "animation_studio_presets", "animation_studio_speech", "animation_studio_batches"]


def forward(apps, editor):
    from modules.tenancy.database import tenant_database_context
    Organization = apps.get_model("enterprise", "Organization")
    Run = apps.get_model("execution", "Run")
    Project = apps.get_model("animation_studio", "AnimationProject")
    Version = apps.get_model("animation_studio", "AnimationVersion")
    Application = apps.get_model("applications", "Application")
    for org in Organization.objects.all().iterator():
        with tenant_database_context(org.id):
            apps_owned = {str(a.id): a for a in Application.objects.filter(organization_id=org.id, slug="animation-studio")}
            runs = list(Run.objects.filter(organization_id=org.id, executor_key="animation-studio", source_type="application", input__action="generate").order_by("created_at", "id"))
            by_id = {str(r.id): r for r in runs}
            linked = {str(v.run_id): v.project_id for v in Version.objects.filter(organization_id=org.id)}
            def attach(run, seen):
                key = str(run.id)
                if key in linked: return linked[key]
                app = apps_owned.get(run.source_id)
                if not app: return None
                parent = by_id.get(str(run.input.get("source_run_id", "")))
                project_id = None
                if parent and parent.owner_id == run.owner_id and parent.source_id == run.source_id and str(parent.id) not in seen:
                    project_id = attach(parent, seen | {key})
                document = {"schema_version": 1, **run.input, "source_run_id": key}
                if not project_id:
                    project_id = Project.objects.create(organization_id=org.id, application_id=app.id, owner_id=run.owner_id,
                        title=str(run.output_summary.get("title") or run.input.get("prompt") or "历史作品")[:200], draft=document).id
                Version.objects.get_or_create(run_id=run.id, defaults={"organization_id": org.id, "project_id": project_id, "document": document, "note": str(run.input.get("prompt", ""))[:1000]})
                linked[key] = project_id
                return project_id
            for run in runs: attach(run, set())
    if editor.connection.vendor == "postgresql":
        for table in TABLES:
            editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            editor.execute(f'CREATE POLICY "tenant_isolation" ON "{table}" USING (organization_id = NULLIF(current_setting(\'app.organization_id\', true), \'\')::uuid) WITH CHECK (organization_id = NULLIF(current_setting(\'app.organization_id\', true), \'\')::uuid)')


def backward(apps, editor):
    if editor.connection.vendor == "postgresql":
        for table in TABLES:
            editor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            editor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("animation_studio", "0003_animationasset_archived_animationasset_category_and_more")]
    operations = [migrations.RunPython(forward, backward)]

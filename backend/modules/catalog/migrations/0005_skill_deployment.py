import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def install_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE "skill_deployments" ENABLE ROW LEVEL SECURITY')
        cursor.execute('ALTER TABLE "skill_deployments" FORCE ROW LEVEL SECURITY')
        cursor.execute(
            'CREATE POLICY "tenant_isolation" ON "skill_deployments" '
            "USING (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid)"
        )


def remove_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP POLICY IF EXISTS "tenant_isolation" ON "skill_deployments"')
        cursor.execute('ALTER TABLE "skill_deployments" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0004_deploy_seeded_general_agent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SkillDeployment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("environment", models.CharField(choices=[("development", "Development"), ("staging", "Staging"), ("production", "Production")], max_length=20)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("previous_revision", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="previous_deployments", to="catalog.skillrevision")),
                ("revision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="deployments", to="catalog.skillrevision")),
                ("skill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deployments", to="applications.skill")),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "skill_deployments"},
        ),
        migrations.AddConstraint(
            model_name="skilldeployment",
            constraint=models.UniqueConstraint(fields=("skill", "environment"), name="unique_skill_deployment_environment"),
        ),
        migrations.RunPython(install_rls, remove_rls),
    ]

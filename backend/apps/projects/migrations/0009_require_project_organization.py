import uuid

import django.db.models.deletion
from django.db import migrations, models


def backfill_project_organizations(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Membership = apps.get_model("enterprise", "Membership")
    Organization = apps.get_model("enterprise", "Organization")
    for project in Project.objects.filter(organization_id__isnull=True).iterator():
        membership = Membership.objects.filter(
            user_id=project.user_id,
            is_active=True,
            organization__is_active=True,
        ).order_by("created_at", "id").first()
        if membership is None:
            organization = Organization.objects.create(
                id=uuid.uuid4(),
                owner_id=project.user_id,
                name=f"User {project.user_id} Workspace",
                slug=f"project-user-{project.user_id}-{uuid.uuid4().hex[:8]}",
                is_active=True,
            )
            Membership.objects.create(
                organization_id=organization.id,
                user_id=project.user_id,
                role="owner",
                is_active=True,
            )
            organization_id = organization.id
        else:
            organization_id = membership.organization_id
        Project.objects.filter(pk=project.pk).update(
            organization_id=organization_id)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("enterprise", "0005_external_identity"),
        ("projects", "0008_project_workflow_project_project_has_single_origin"),
    ]

    operations = [
        migrations.RunPython(
            backfill_project_organizations,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="project",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="projects",
                to="enterprise.organization",
            ),
        ),
    ]

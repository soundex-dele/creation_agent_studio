import django.db.models.deletion
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import migrations, models


def migrate_workflow_origins(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    Workflow = apps.get_model('workflows', 'Workflow')

    for project in Project.objects.all().iterator():
        if not isinstance(project.structure, dict):
            continue
        structure = dict(project.structure)
        workflow_id = structure.pop('workflow_id', None)
        try:
            workflow_exists = bool(
                workflow_id and Workflow.objects.filter(pk=workflow_id).exists())
        except (TypeError, ValueError, ValidationError):
            workflow_exists = False
        if workflow_exists:
            Project.objects.filter(pk=project.pk).update(
                workflow_id=workflow_id,
                application_id=None,
                structure=structure,
            )


class Migration(migrations.Migration):
    dependencies = [
        ('applications', '0006_chat_application_subtype'),
        ('enterprise', '0005_external_identity'),
        ('projects', '0007_remove_project_template'),
        ('workflows', '0004_workflow_dag'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='workflow',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='projects',
                to='workflows.workflow',
            ),
        ),
        migrations.RunPython(migrate_workflow_origins, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='project',
            constraint=models.CheckConstraint(
                check=models.Q(
                    ('application__isnull', True),
                    ('workflow__isnull', True),
                    _connector='OR',
                ),
                name='project_has_single_origin',
            ),
        ),
    ]

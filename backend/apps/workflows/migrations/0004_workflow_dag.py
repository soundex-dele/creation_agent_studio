from django.db import migrations, models


def convert_ordered_steps(apps, schema_editor):
    WorkflowStep = apps.get_model("workflows", "WorkflowStep")
    workflow_ids = (
        WorkflowStep.objects.order_by()
        .values_list("workflow_id", flat=True)
        .distinct()
    )
    for workflow_id in workflow_ids.iterator():
        previous_key = None
        steps = WorkflowStep.objects.filter(workflow_id=workflow_id).order_by("order", "id")
        for step in steps.iterator():
            key = f"step-{step.order + 1}-{str(step.id)[:8]}"
            step.key = key
            step.depends_on = [previous_key] if previous_key else []
            step.save(update_fields=("key", "depends_on"))
            previous_key = key


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("workflows", "0003_remove_workflowsteprun_workflow_run_and_more")]

    operations = [
        migrations.AddField(
            model_name="workflowstep",
            name="key",
            field=models.SlugField(default="", max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="workflowstep",
            name="depends_on",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workflowstep",
            name="condition",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="workflowstep",
            name="max_attempts",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.RunPython(convert_ordered_steps, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="workflowstep",
            constraint=models.UniqueConstraint(
                fields=("workflow", "key"), name="unique_workflow_step_key"
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowstep",
            constraint=models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name="workflow_step_attempts_at_least_one",
            ),
        ),
    ]

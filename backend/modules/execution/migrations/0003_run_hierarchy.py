from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("execution", "0002_postgresql_rls")]

    operations = [
        migrations.AddField(
            model_name="run",
            name="node_key",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="run",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="child_runs",
                to="execution.run",
            ),
        ),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.UniqueConstraint(
                condition=models.Q(parent__isnull=False),
                fields=("parent", "node_key"),
                name="unique_child_run_node_key",
            ),
        ),
        migrations.AddIndex(
            model_name="run",
            index=models.Index(
                fields=["parent", "status"], name="run_parent_status_idx"
            ),
        ),
    ]

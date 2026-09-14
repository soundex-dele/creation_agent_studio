from django.db import migrations, models, transaction
import django.db.models.deletion


def backfill_queue(apps, schema_editor):
    Run = apps.get_model("execution", "Run")
    RunQueueEntry = apps.get_model("execution", "RunQueueEntry")
    Organization = apps.get_model("enterprise", "Organization")
    database = schema_editor.connection.alias
    for organization_id in Organization.objects.using(database).values_list(
        "id", flat=True
    ).iterator():
        with transaction.atomic(using=database):
            if schema_editor.connection.vendor == "postgresql":
                with schema_editor.connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)",
                        [str(organization_id)],
                    )
            runs = Run.objects.using(database).filter(
                organization_id=organization_id,
                status="queued",
                current_attempt__isnull=True,
            )
            RunQueueEntry.objects.using(database).bulk_create([
                RunQueueEntry(
                    run_id=run.id,
                    organization_id=run.organization_id,
                    worker_pool=run.executor_kind,
                    executor_key=run.executor_key,
                    priority=run.priority,
                )
                for run in runs.iterator()
            ])


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("execution", "0004_run_waiting_children")]

    operations = [
        migrations.CreateModel(
            name="RunQueueEntry",
            fields=[
                ("organization_id", models.UUIDField(db_index=True)),
                ("worker_pool", models.CharField(db_index=True, max_length=20)),
                ("executor_key", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("priority", models.SmallIntegerField(default=0)),
                ("enqueued_at", models.DateTimeField(auto_now_add=True)),
                ("run", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="queue_entry", serialize=False, to="execution.run")),
            ],
            options={
                "db_table": "run_queue_entries",
                "ordering": ("-priority", "enqueued_at", "run_id"),
            },
        ),
        migrations.AddIndex(
            model_name="runqueueentry",
            index=models.Index(fields=["worker_pool", "-priority", "enqueued_at"], name="run_queue_claim_idx"),
        ),
        migrations.RunPython(backfill_queue, migrations.RunPython.noop),
    ]

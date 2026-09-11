import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("v2_execution", "0005_execution_invariants"),
    ]

    operations = [
        migrations.CreateModel(
            name="RunEventSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("through_sequence", models.PositiveBigIntegerField()),
                ("schema_version", models.PositiveSmallIntegerField(default=1)),
                ("projection", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="v2_tenancy.organization",
                    ),
                ),
                (
                    "run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="event_snapshot",
                        to="v2_execution.run",
                    ),
                ),
            ],
            options={"db_table": "v2_run_event_snapshots"},
        ),
        migrations.AddConstraint(
            model_name="runeventsnapshot",
            constraint=models.CheckConstraint(
                check=models.Q(("through_sequence__gte", 1)),
                name="v2_run_snapshot_sequence_positive",
            ),
        ),
    ]

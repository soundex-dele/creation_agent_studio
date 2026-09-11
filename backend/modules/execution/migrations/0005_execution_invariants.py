from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("v2_execution", "0004_suspension_retry_budget")]

    operations = [
        migrations.AddConstraint(
            model_name="run",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(
                        status="waiting_input",
                        pending_input_request_id__isnull=False,
                        pending_input_kind__in=("answer", "permission"),
                        pending_input_expires_at__isnull=False,
                    )
                    | (
                        ~models.Q(status="waiting_input")
                        & models.Q(pending_input_request_id__isnull=True)
                        & models.Q(pending_input_kind="")
                        & models.Q(pending_input_expires_at__isnull=True)
                    )
                ),
                name="v2_run_pending_input_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="runattempt",
            constraint=models.UniqueConstraint(
                condition=models.Q(finished_at__isnull=True),
                fields=("run",),
                name="v2_one_active_attempt_per_run",
            ),
        ),
    ]

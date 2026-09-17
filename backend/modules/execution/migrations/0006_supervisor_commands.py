from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('execution', '0005_run_queue_entry')]

    operations = [
        migrations.RemoveConstraint(
            model_name='run', name='run_pending_input_consistent'
        ),
        migrations.AlterField(
            model_name='run',
            name='pending_input_kind',
            field=models.CharField(
                blank=True,
                choices=[
                    ('answer', 'Answer'),
                    ('permission', 'Permission'),
                    ('plan_approval', 'Plan approval'),
                ],
                default='',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='runcommand',
            name='type',
            field=models.CharField(
                choices=[
                    ('answer', 'Answer'),
                    ('grant_permission', 'Grant permission'),
                    ('deny_permission', 'Deny permission'),
                    ('approve_plan', 'Approve plan'),
                    ('revise_plan', 'Revise plan'),
                    ('cancel', 'Cancel'),
                ],
                max_length=30,
            ),
        ),
        migrations.AddConstraint(
            model_name='run',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status='waiting_input',
                        pending_input_request_id__isnull=False,
                        pending_input_kind__in=(
                            'answer', 'permission', 'plan_approval'
                        ),
                        pending_input_expires_at__isnull=False,
                    )
                    | (
                        ~models.Q(status='waiting_input')
                        & models.Q(pending_input_request_id__isnull=True)
                        & models.Q(pending_input_kind='')
                        & models.Q(pending_input_expires_at__isnull=True)
                    )
                ),
                name='run_pending_input_consistent',
            ),
        ),
    ]

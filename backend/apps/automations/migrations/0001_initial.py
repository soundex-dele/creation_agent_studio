import uuid

import django.db.models.deletion
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import migrations, models
from django.utils import timezone
from croniter import croniter


def migrate_legacy_automations(apps, schema_editor):
    Automation = apps.get_model("automations", "Automation")
    Application = apps.get_model("applications", "Application")
    Workflow = apps.get_model("workflows", "Workflow")

    for automation in Automation.objects.select_related("organization__owner"):
        automation.public_id = uuid.uuid4()
        automation.created_by_id = automation.organization.owner_id
        automation.default_input = dict(automation.input_mapping or {})
        automation.timezone = "UTC"
        automation.blocked_reason = ""
        supported_target = False
        if automation.target_type == "application":
            try:
                target_id = int(automation.target_id)
            except (TypeError, ValueError):
                target_id = None
            application = Application.objects.filter(
                pk=target_id, organization_id=automation.organization_id
            ).first()
            if application:
                automation.application_id = application.pk
                supported_target = True
        elif automation.target_type == "workflow":
            try:
                workflow = Workflow.objects.filter(
                    pk=automation.target_id,
                    organization_id=automation.organization_id,
                ).first()
            except (ValidationError, ValueError):
                workflow = None
            if workflow:
                automation.workflow_id = workflow.pk
                supported_target = True

        valid_schedule = (
            automation.trigger_type != "schedule"
            or (
                len(str(automation.schedule or "").split()) == 5
                and croniter.is_valid(automation.schedule)
            )
        )
        if automation.trigger_type == "schedule" and supported_target and valid_schedule:
            automation.schedule_kind = "cron"
            automation.status = "active" if automation.is_active else "paused"
            automation.next_run_at = timezone.now() if automation.is_active else None
        elif automation.trigger_type == "webhook" and supported_target:
            automation.status = "paused"
            automation.blocked_reason = "请轮换 Webhook 密钥后再启用。"
        elif automation.trigger_type == "schedule" and not valid_schedule:
            automation.status = "blocked"
            automation.blocked_reason = "旧版 Cron 表达式无效，请修正后重新启用。"
        else:
            automation.status = "blocked"
            automation.blocked_reason = "旧版 Agent 或 Event 自动化不再受支持，请改建为应用或工作流自动化。"
        automation.is_active = automation.status == "active"
        automation.save(update_fields=[
            "public_id", "created_by", "default_input", "timezone", "application",
            "workflow", "schedule_kind", "status", "next_run_at",
            "blocked_reason", "is_active",
        ])


class Migration(migrations.Migration):
    initial = True
    # PostgreSQL may retain deferred constraint events across the legacy data
    # copy and the constraints added later in this migration.
    atomic = False

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("enterprise", "0006_evaluation_run_execution"),
        ("applications", "0007_generalize_default_experience"),
        ("workflows", "0006_workflow_output_mapping"),
        ("execution", "0005_run_queue_entry"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Automation",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("name", models.CharField(max_length=160)),
                        ("trigger_type", models.CharField(choices=[("schedule", "Schedule"), ("webhook", "Webhook"), ("event", "Legacy event")], default="webhook", max_length=30)),
                        ("target_type", models.CharField(choices=[("application", "Application"), ("workflow", "Workflow"), ("agent", "Legacy agent")], max_length=30)),
                        ("target_id", models.CharField(max_length=160)),
                        ("schedule", models.CharField(blank=True, max_length=120)),
                        ("event_name", models.CharField(blank=True, max_length=160)),
                        ("input_mapping", models.JSONField(blank=True, default=dict)),
                        ("is_active", models.BooleanField(default=True)),
                        ("last_triggered_at", models.DateTimeField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                    ],
                    options={"db_table": "automation_triggers", "ordering": ("-updated_at", "-id")},
                )
            ],
            database_operations=[],
        ),
        migrations.AddField(model_name="automation", name="description", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="automation", name="created_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_automations", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="automation", name="status", field=models.CharField(choices=[("draft", "Draft"), ("active", "Active"), ("paused", "Paused"), ("blocked", "Blocked"), ("archived", "Archived")], db_index=True, default="draft", max_length=20)),
        migrations.AddField(model_name="automation", name="schedule_kind", field=models.CharField(blank=True, choices=[("once", "Once"), ("cron", "Cron")], default="", max_length=20)),
        migrations.AddField(model_name="automation", name="timezone", field=models.CharField(default="Asia/Shanghai", max_length=64)),
        migrations.AddField(model_name="automation", name="run_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="automation", name="next_run_at", field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="automation", name="last_scheduled_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="automation", name="application", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="automations", to="applications.application")),
        migrations.AddField(model_name="automation", name="workflow", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="automations", to="workflows.workflow")),
        migrations.AddField(model_name="automation", name="default_input", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="automation", name="public_id", field=models.UUIDField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="automation", name="secret_digest", field=models.CharField(blank=True, default="", max_length=128)),
        migrations.AddField(model_name="automation", name="secret_prefix", field=models.CharField(blank=True, default="", max_length=16)),
        migrations.AddField(model_name="automation", name="secret_rotated_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="automation", name="blocked_reason", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="automation", name="archived_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.CreateModel(
            name="AutomationInvocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(choices=[("schedule", "Schedule"), ("webhook", "Webhook"), ("manual", "Manual")], max_length=20)),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("dedup_key", models.CharField(max_length=200)),
                ("request_fingerprint", models.CharField(blank=True, default="", max_length=64)),
                ("outcome", models.CharField(choices=[("pending", "Pending"), ("dispatched", "Dispatched"), ("failed", "Failed"), ("skipped_capacity", "Skipped: capacity")], db_index=True, default="pending", max_length=30)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("automation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invocations", to="automations.automation")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="automation_invocations", to="enterprise.organization")),
                ("run", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="automation_invocation", to="execution.run")),
            ],
            options={"db_table": "automation_invocations", "ordering": ("-created_at",)},
        ),
        migrations.RunPython(migrate_legacy_automations, migrations.RunPython.noop),
        migrations.AlterField(model_name="automation", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.AddConstraint(model_name="automation", constraint=models.CheckConstraint(condition=~(models.Q(("application__isnull", False), ("workflow__isnull", False))), name="automation_at_most_one_target")),
        migrations.AddIndex(model_name="automation", index=models.Index(fields=["status", "next_run_at"], name="automation_due_idx")),
        migrations.AddConstraint(model_name="automationinvocation", constraint=models.UniqueConstraint(fields=("automation", "dedup_key"), name="unique_automation_invocation_dedup")),
    ]

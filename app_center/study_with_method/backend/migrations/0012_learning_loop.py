import uuid

import django.db.models.deletion
from django.db import migrations, models


TENANT_TABLES = (
    "study_goals",
    "study_diagnostic_assessments",
    "study_diagnostic_results",
)


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("study_with_method", "0011_answer_card")]

    operations = [
        migrations.AddField(
            model_name="studyprofile",
            name="weekly_minutes",
            field=models.PositiveSmallIntegerField(default=315),
        ),
        migrations.AddField(
            model_name="studyprofile",
            name="exam_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mistakerecord",
            name="is_archived",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="reviewschedule",
            name="repetition_streak",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="reviewschedule",
            name="lapse_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="reviewschedule",
            name="difficulty",
            field=models.PositiveSmallIntegerField(default=5),
        ),
        migrations.AddField(
            model_name="reviewschedule",
            name="last_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="knowledgemastery",
            name="confidence",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="knowledgemastery",
            name="last_evidence_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="StudyGoal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subject", models.CharField(choices=[("chinese", "语文"), ("math", "数学"), ("english", "英语"), ("physics", "物理"), ("chemistry", "化学"), ("biology", "生物"), ("politics", "思想政治"), ("history", "历史"), ("geography", "地理")], db_index=True, max_length=32)),
                ("exam_date", models.DateField(blank=True, null=True)),
                ("target_score", models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ("weekly_minutes", models.PositiveSmallIntegerField(default=315)),
                ("focus_chapters", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="goals", to="study_with_method.studyprofile")),
            ],
            options={"db_table": "study_goals", "ordering": ("exam_date", "subject")},
        ),
        migrations.AddConstraint(
            model_name="studygoal",
            constraint=models.UniqueConstraint(fields=("profile", "subject"), name="unique_study_goal_subject"),
        ),
        migrations.CreateModel(
            name="DiagnosticAssessment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subjects", models.JSONField(default=list)),
                ("questions", models.JSONField(default=list)),
                ("status", models.CharField(choices=[("in_progress", "进行中"), ("completed", "已完成"), ("skipped", "已跳过")], db_index=True, default="in_progress", max_length=20)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="diagnostics", to="study_with_method.studyprofile")),
            ],
            options={"db_table": "study_diagnostic_assessments", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="DiagnosticResult",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subject", models.CharField(choices=[("chinese", "语文"), ("math", "数学"), ("english", "英语"), ("physics", "物理"), ("chemistry", "化学"), ("biology", "生物"), ("politics", "思想政治"), ("history", "历史"), ("geography", "地理")], db_index=True, max_length=32)),
                ("knowledge_point_code", models.CharField(blank=True, max_length=180)),
                ("knowledge_point_name", models.CharField(blank=True, max_length=160)),
                ("score", models.PositiveSmallIntegerField(default=0)),
                ("confidence", models.PositiveSmallIntegerField(default=0)),
                ("responses", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assessment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="results", to="study_with_method.diagnosticassessment")),
                ("knowledge_point", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="diagnostic_results", to="study_with_method.curriculumnode")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="diagnostic_results", to="study_with_method.studyprofile")),
            ],
            options={"db_table": "study_diagnostic_results", "ordering": ("subject", "score")},
        ),
        migrations.AddConstraint(
            model_name="diagnosticresult",
            constraint=models.UniqueConstraint(fields=("assessment", "subject", "knowledge_point_code"), name="unique_study_diagnostic_result"),
        ),
        migrations.RunPython(enable_rls, disable_rls),
    ]

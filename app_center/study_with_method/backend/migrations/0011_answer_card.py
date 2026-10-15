import uuid

import django.db.models.deletion
from django.db import migrations, models


def enable_answer_card_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = "study_answer_cards"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        cursor.execute(
            f'CREATE POLICY "tenant_isolation" ON "{table}" '
            "USING (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid)"
        )


def disable_answer_card_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP POLICY IF EXISTS "tenant_isolation" ON "study_answer_cards"')
        cursor.execute('ALTER TABLE "study_answer_cards" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("study_with_method", "0010_mistakecheckin")]

    operations = [
        migrations.AlterField(
            model_name="curriculumnode",
            name="node_type",
            field=models.CharField(
                choices=[
                    ("module", "模块"),
                    ("volume", "册次"),
                    ("chapter", "章节"),
                    ("section", "小节"),
                    ("knowledge_point", "知识点"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="AnswerCard",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subject", models.CharField(choices=[("chinese", "语文"), ("math", "数学"), ("english", "英语"), ("physics", "物理"), ("chemistry", "化学"), ("biology", "生物"), ("politics", "思想政治"), ("history", "历史"), ("geography", "地理")], db_index=True, max_length=32)),
                ("grade_stage", models.CharField(choices=[("high_1", "高一"), ("high_2", "高二"), ("high_3", "高三")], max_length=32)),
                ("curriculum_version", models.CharField(db_index=True, max_length=120)),
                ("knowledge_point_code", models.CharField(db_index=True, max_length=180)),
                ("knowledge_point_name", models.CharField(max_length=160)),
                ("questions", models.JSONField(default=list)),
                ("results", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("ready", "待提交"), ("completed", "已完成")], db_index=True, default="ready", max_length=20)),
                ("score", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("knowledge_point", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="answer_cards", to="study_with_method.curriculumnode")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="answer_cards", to="study_with_method.studyprofile")),
            ],
            options={"db_table": "study_answer_cards", "ordering": ("-created_at",)},
        ),
        migrations.RunPython(enable_answer_card_rls, disable_answer_card_rls),
    ]

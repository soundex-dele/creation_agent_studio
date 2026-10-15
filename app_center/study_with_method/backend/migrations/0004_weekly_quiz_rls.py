from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE "study_weekly_quizzes" ENABLE ROW LEVEL SECURITY')
        cursor.execute('ALTER TABLE "study_weekly_quizzes" FORCE ROW LEVEL SECURITY')
        cursor.execute(
            'CREATE POLICY "tenant_isolation" ON "study_weekly_quizzes" '
            "USING (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF(current_setting("
            "'app.organization_id', true), '')::uuid)"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'DROP POLICY IF EXISTS "tenant_isolation" ON "study_weekly_quizzes"'
        )
        cursor.execute('ALTER TABLE "study_weekly_quizzes" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("study_with_method", "0003_studyprofile_grade_stage_and_more")]
    operations = [migrations.RunPython(enable_rls, disable_rls)]

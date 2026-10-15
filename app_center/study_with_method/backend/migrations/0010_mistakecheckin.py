import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def backfill_mistake_check_ins(apps, schema_editor):
    MistakeRecord = apps.get_model("study_with_method", "MistakeRecord")
    MistakeCheckIn = apps.get_model("study_with_method", "MistakeCheckIn")
    database_alias = schema_editor.connection.alias
    is_postgresql = schema_editor.connection.vendor == "postgresql"
    if is_postgresql:
        # Existing study tables use FORCE RLS. The migration connection owns the
        # table, so temporarily removing FORCE lets it see every tenant for the
        # backfill while the policy remains enabled for other connections.
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE "study_mistakes" NO FORCE ROW LEVEL SECURITY')
    try:
        seen = set()
        check_ins = []
        mistakes = MistakeRecord.objects.using(database_alias).all().only(
            "organization_id", "profile_id", "subject", "created_at"
        )
        for mistake in mistakes.iterator():
            created_at = mistake.created_at
            checked_on = (
                timezone.localtime(created_at).date()
                if timezone.is_aware(created_at)
                else created_at.date()
            )
            key = (mistake.profile_id, mistake.subject, checked_on)
            if key in seen:
                continue
            seen.add(key)
            check_ins.append(MistakeCheckIn(
                organization_id=mistake.organization_id,
                profile_id=mistake.profile_id,
                subject=mistake.subject,
                checked_on=checked_on,
            ))
        MistakeCheckIn.objects.using(database_alias).bulk_create(
            check_ins, ignore_conflicts=True
        )
    finally:
        if is_postgresql:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute('ALTER TABLE "study_mistakes" FORCE ROW LEVEL SECURITY')


def enable_check_in_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = "study_mistake_check_ins"
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


def disable_check_in_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = "study_mistake_check_ins"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
        cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("study_with_method", "0009_problem_source_attachment")]

    operations = [
        migrations.CreateModel(
            name="MistakeCheckIn",
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
                (
                    "subject",
                    models.CharField(
                        choices=[
                            ("chinese", "语文"),
                            ("math", "数学"),
                            ("english", "英语"),
                            ("physics", "物理"),
                            ("chemistry", "化学"),
                            ("biology", "生物"),
                            ("politics", "思想政治"),
                            ("history", "历史"),
                            ("geography", "地理"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("checked_on", models.DateField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="enterprise.organization",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mistake_check_ins",
                        to="study_with_method.studyprofile",
                    ),
                ),
            ],
            options={
                "db_table": "study_mistake_check_ins",
                "ordering": ("-checked_on", "-created_at"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile", "subject", "checked_on"),
                        name="unique_study_mistake_check_in",
                    )
                ],
            },
        ),
        migrations.RunPython(backfill_mistake_check_ins, migrations.RunPython.noop),
        migrations.RunPython(enable_check_in_rls, disable_check_in_rls),
    ]

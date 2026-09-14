from django.db import migrations


def create_missing_skill_drafts(apps, schema_editor):
    Skill = apps.get_model("applications", "Skill")
    SkillDraft = apps.get_model("catalog", "SkillDraft")
    Organization = apps.get_model("enterprise", "Organization")
    for organization_id in Organization.objects.values_list("id", flat=True).iterator():
        if schema_editor.connection.vendor == "postgresql":
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.organization_id', %s, true)",
                    [str(organization_id)],
                )
        for skill in Skill.objects.filter(organization_id=organization_id).iterator():
            SkillDraft.objects.get_or_create(
                skill_id=skill.id,
                defaults={
                    "organization_id": skill.organization_id,
                    "updated_by_id": skill.owner_id,
                    "content": {
                        "source_type": skill.source_type,
                        "source_uri": skill.source_uri,
                        "artifact_key": skill.artifact_key,
                        "manifest": skill.manifest,
                        "content_hash": skill.content_hash,
                    },
                },
            )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0005_skill_deployment")]

    operations = [
        migrations.RunPython(create_missing_skill_drafts, migrations.RunPython.noop),
    ]

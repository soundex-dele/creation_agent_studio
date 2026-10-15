from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def backfill_sources(apps, schema_editor):
    Handoff = apps.get_model('project_promotion', 'Handoff')
    Handoff.objects.using(schema_editor.connection.alias).filter(topic__isnull=False).update(source_type='topic')


def require_legacy_sources(apps, schema_editor):
    Handoff = apps.get_model('project_promotion', 'Handoff')
    if Handoff.objects.using(schema_editor.connection.alias).filter(source_type='materials').exists():
        raise IrreversibleError('素材探索交接无法转换为旧版选题或文案交接，请保留当前迁移。')


class Migration(migrations.Migration):
    dependencies = [('project_promotion', '0005_handoff_platform_handoff_snapshot_handoff_topic_and_more')]
    operations = [
        migrations.RemoveConstraint(model_name='handoff', name='promotion_handoff_source'),
        migrations.AddField(model_name='handoff', name='source_type', field=models.CharField(
            max_length=20, default='version', choices=[('version', '文案版本'), ('topic', '选题'), ('materials', '素材探索')])),
        migrations.RunPython(backfill_sources, require_legacy_sources),
        migrations.AddConstraint(model_name='handoff', constraint=models.CheckConstraint(
            condition=(models.Q(source_type='version', version__isnull=False, topic__isnull=True)
                       | models.Q(source_type='topic', version__isnull=True, topic__isnull=False)
                       | models.Q(source_type='materials', version__isnull=True, topic__isnull=True)),
            name='promotion_handoff_source')),
    ]

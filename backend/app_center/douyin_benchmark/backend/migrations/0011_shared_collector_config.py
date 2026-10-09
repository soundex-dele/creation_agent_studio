from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def keep_latest_config(apps, schema_editor):
    connection = schema_editor.connection
    config_model = apps.get_model('douyin_benchmark', 'CollectorConfig')
    organization_model = apps.get_model('enterprise', 'Organization')
    with connection.cursor() as cursor:
        previous = None
        if connection.vendor == 'postgresql':
            cursor.execute("SELECT current_setting('app.organization_id', true)")
            previous = cursor.fetchone()[0]
        try:
            for organization_id in organization_model.objects.using(connection.alias).values_list('pk', flat=True).iterator():
                if connection.vendor == 'postgresql':
                    cursor.execute("SELECT set_config('app.organization_id', %s, true)", [str(organization_id)])
                configs = config_model.objects.using(connection.alias).filter(organization_id=organization_id)
                retained = set()
                for config in configs.order_by('-updated_at', '-pk').iterator():
                    if config.application_id in retained:
                        configs.filter(pk=config.pk).delete()
                    else:
                        retained.add(config.application_id)
        finally:
            if connection.vendor == 'postgresql':
                cursor.execute("SELECT set_config('app.organization_id', %s, true)", [previous or ''])


class Migration(migrations.Migration):
    dependencies = [('douyin_benchmark', '0010_collector_cookies_plaintext')]
    operations = [
        migrations.RemoveConstraint(model_name='collectorconfig', name='dy_collector_owner_unique'),
        migrations.RunPython(keep_latest_config, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='collectorconfig', name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name='collectorconfig',
            constraint=models.UniqueConstraint(fields=('organization', 'application'), name='dy_collector_application_unique'),
        ),
    ]

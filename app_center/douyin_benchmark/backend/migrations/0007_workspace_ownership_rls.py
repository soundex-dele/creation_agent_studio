from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


DIRECT = ['creatorprofile', 'digest', 'idea', 'inspiration', 'notification', 'publication', 'subscription']
POLICIES = {f'douyin_benchmark_{name}': "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid" for name in DIRECT + ['task']}
POLICIES.update({
    'douyin_benchmark_tasksource': 'task_id IN (SELECT id FROM douyin_benchmark_task) AND account_id IN (SELECT id FROM douyin_benchmark_account)',
    'douyin_benchmark_metricobservation': 'task_id IN (SELECT id FROM douyin_benchmark_task) AND work_id IN (SELECT id FROM douyin_benchmark_work)',
    'douyin_benchmark_commentbatch': 'task_id IN (SELECT id FROM douyin_benchmark_task) AND work_id IN (SELECT id FROM douyin_benchmark_work)',
    'douyin_benchmark_comment': 'batch_id IN (SELECT id FROM douyin_benchmark_commentbatch)',
    'douyin_benchmark_subscription_tracked_works': 'subscription_id IN (SELECT id FROM douyin_benchmark_subscription) AND work_id IN (SELECT id FROM douyin_benchmark_work)',
})


def backfill(apps, schema_editor):
    from modules.tenancy.database import tenant_database_context
    Task = apps.get_model('douyin_benchmark', 'Task')
    Org = apps.get_model('enterprise', 'Organization')
    for org_id in Org.objects.values_list('pk', flat=True).iterator():
        with tenant_database_context(org_id):
            for task in Task.objects.filter(account__organization_id=org_id).select_related('account').iterator(chunk_size=500):
                Task.objects.filter(pk=task.pk).update(organization_id=org_id, application_id=task.account.application_id, owner_id=task.account.owner_id)


def enable(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for table, predicate in POLICIES.items():
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            cursor.execute(f'CREATE POLICY tenant_isolation ON "{table}" USING ({predicate}) WITH CHECK ({predicate})')


def disable(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for table in reversed(POLICIES):
            cursor.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            if table == 'douyin_benchmark_task':
                cursor.execute(f'CREATE POLICY tenant_isolation ON "{table}" USING (account_id IN (SELECT id FROM douyin_benchmark_account)) WITH CHECK (account_id IN (SELECT id FROM douyin_benchmark_account))')
            else:
                cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [('douyin_benchmark', '0006_comment_commentbatch_creatorprofile_digest_idea_and_more')]
    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
        *[migrations.AlterField(model_name='task', name=name, field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=target)) for name, target in [
            ('organization', 'enterprise.organization'), ('application', 'applications.application'), ('owner', settings.AUTH_USER_MODEL)]],
        migrations.RunPython(enable, disable),
    ]

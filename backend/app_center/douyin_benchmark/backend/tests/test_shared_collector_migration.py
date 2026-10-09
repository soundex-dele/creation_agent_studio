import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from .test_douyin import ctx


@pytest.mark.django_db(transaction=True)
def test_shared_config_migration_keeps_latest_credentials_together(ctx):
    before = [('douyin_benchmark', '0010_collector_cookies_plaintext')]
    after = [('douyin_benchmark', '0011_shared_collector_config')]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    try:
        historical = executor.loader.project_state(before).apps
        config_model = historical.get_model('douyin_benchmark', 'CollectorConfig')
        config_model.objects.create(organization_id=ctx.org.pk, application_id=ctx.app.pk,
                                    owner_id=ctx.owner.pk, cookies='UIFID_TEMP=old', user_agent='old-UA')
        latest = config_model.objects.create(organization_id=ctx.org.pk, application_id=ctx.app.pk,
                                             owner_id=ctx.reader.pk, cookies='UIFID_TEMP=new', user_agent='new-UA')
        MigrationExecutor(connection).migrate(after)
        from ..models import CollectorConfig
        saved = CollectorConfig.objects.get(application=ctx.app)
        assert saved.pk == latest.pk
        assert saved.cookies == 'UIFID_TEMP=new' and saved.user_agent == 'new-UA'
        assert saved.owner_id == ctx.reader.pk
    finally:
        MigrationExecutor(connection).migrate(after)

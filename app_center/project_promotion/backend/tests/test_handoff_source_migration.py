import pytest
from django.contrib.auth import get_user_model
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from apps.applications.models import Application, ApplicationCategory


@pytest.mark.django_db(transaction=True)
def test_backfills_both_legacy_sources_and_enforces_new_constraint():
    before = [('project_promotion', '0005_handoff_platform_handoff_snapshot_handoff_topic_and_more')]
    after = [('project_promotion', '0006_handoff_source_type')]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    try:
        old = executor.loader.project_state(before).apps
        owner = get_user_model().objects.create_user(username='migration-explorer')
        org = owner.owned_organizations.get()
        category = ApplicationCategory.objects.create(name='Migration', slug='migration-explorer')
        app = Application.objects.create(organization=org, category=category, name='Promotion', slug='project-promotion', created_by=owner)
        fields = dict(organization_id=org.pk, application_id=app.pk, owner_id=owner.pk, title='历史资料')
        case = old.get_model('project_promotion', 'Case').objects.create(**fields)
        topic = old.get_model('project_promotion', 'Topic').objects.create(**fields, case_id=case.pk)
        channel = old.get_model('project_promotion', 'Channel').objects.create(**fields, topic_id=topic.pk, platform='wechat')
        version = old.get_model('project_promotion', 'Version').objects.create(organization_id=org.pk, channel_id=channel.pk, number=1)
        Handoff = old.get_model('project_promotion', 'Handoff')
        legacy_version = Handoff.objects.create(**fields, target_application_id=app.pk, version_id=version.pk, draft={'source': '历史文案'})
        legacy_topic = Handoff.objects.create(**fields, target_application_id=app.pk, topic_id=topic.pk, draft={'source': '历史选题'})
    finally:
        MigrationExecutor(connection).migrate(after)
    from ..models import Handoff
    assert Handoff.objects.get(pk=legacy_version.pk).source_type == 'version'
    assert Handoff.objects.get(pk=legacy_topic.pk).source_type == 'topic'
    assert Handoff.objects.get(pk=legacy_topic.pk).draft == {'source': '历史选题'}
    Handoff.objects.create(**fields, target_application_id=app.pk, source_type='materials', snapshot={'cases': []})
    with pytest.raises(IntegrityError), transaction.atomic():
        Handoff.objects.create(**fields, target_application_id=app.pk, source_type='topic')

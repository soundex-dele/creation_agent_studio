import hashlib
import json

from django.db import migrations


def publish_initial_agent_versions(apps, schema_editor):
    Agent = apps.get_model('agents', 'Agent')
    AgentDraft = apps.get_model('catalog', 'AgentDraft')
    AgentRevision = apps.get_model('catalog', 'AgentRevision')
    database = schema_editor.connection.alias

    agents = Agent.objects.using(database).filter(
        kind='standard',
        is_active=True,
        organization_id__isnull=False,
        revisions__isnull=True,
    ).distinct()
    for agent in agents.iterator():
        draft = AgentDraft.objects.using(database).filter(agent_id=agent.id).first()
        if draft is None:
            continue
        content = dict(draft.content or {})
        content.setdefault('version', '1.0.0')
        if content != draft.content:
            draft.content = content
            draft.version += 1
            draft.save(update_fields=['content', 'version', 'updated_at'])
        encoded = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
        AgentRevision.objects.using(database).create(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            revision_no=1,
            schema_version=1,
            content=content,
            content_hash=hashlib.sha256(encoded).hexdigest(),
            release_notes='Initial version 1.0.0',
            created_by_id=agent.created_by_id,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('agents', '0007_agent_kind_supervisor_profile'),
        ('catalog', '0007_single_active_deployment'),
    ]

    operations = [
        migrations.RunPython(
            publish_initial_agent_versions,
            migrations.RunPython.noop,
        ),
    ]

import hashlib
import json

from django.conf import settings
from django.db import migrations


def _content_hash(content):
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def deploy_seeded_general_agent(apps, schema_editor):
    if not settings.SINGLE_TENANT_MODE:
        return

    Agent = apps.get_model('agents', 'Agent')
    AgentDraft = apps.get_model('catalog', 'AgentDraft')
    AgentRevision = apps.get_model('catalog', 'AgentRevision')
    AgentDeployment = apps.get_model('catalog', 'AgentDeployment')

    for agent in Agent.objects.filter(slug='general', is_public=True).iterator():
        if agent.organization_id is None:
            continue
        if schema_editor.connection.vendor == 'postgresql':
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.organization_id', %s, true)",
                    [str(agent.organization_id)],
                )
        if AgentDeployment.objects.filter(
            agent_id=agent.id,
            environment='production',
        ).exists():
            continue

        revision = AgentRevision.objects.filter(
            agent_id=agent.id,
        ).order_by('-revision_no').first()
        if revision is None:
            draft = AgentDraft.objects.filter(agent_id=agent.id).first()
            if draft is None:
                continue
            revision = AgentRevision.objects.create(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                revision_no=1,
                schema_version=1,
                content=draft.content,
                content_hash=_content_hash(draft.content),
                release_notes='Initial deployment for the built-in general agent.',
                created_by_id=agent.created_by_id,
            )

        AgentDeployment.objects.create(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            environment='production',
            revision_id=revision.id,
            config_override={},
            version=1,
            updated_by_id=agent.created_by_id,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('agents', '0006_move_agent_definition_to_catalog'),
        ('catalog', '0003_chatapplicationrevision'),
    ]

    operations = [
        migrations.RunPython(
            deploy_seeded_general_agent,
            migrations.RunPython.noop,
        ),
    ]

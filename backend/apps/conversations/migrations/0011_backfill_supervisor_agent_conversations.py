from django.db import migrations


def backfill_supervisor_agent_conversations(apps, schema_editor):
    Agent = apps.get_model('agents', 'Agent')
    Conversation = apps.get_model('conversations', 'Conversation')
    Message = apps.get_model('conversations', 'Message')
    Run = apps.get_model('execution', 'Run')

    children = Run.objects.filter(
        source_type='supervisor_task',
        definition_snapshot__supervisor_target_type='agent',
    ).select_related('parent').order_by('created_at')
    for child in children.iterator():
        snapshot = dict(child.definition_snapshot or {})
        if snapshot.get('conversation_id'):
            continue
        try:
            agent_id = int(snapshot.get('supervisor_target_id'))
        except (TypeError, ValueError):
            continue
        if not Agent.objects.filter(pk=agent_id).exists():
            continue
        task = (child.input or {}).get('supervisor_task') or {}
        root_snapshot = (
            child.parent.definition_snapshot
            if child.parent_id and child.parent else {}
        ) or {}
        supervisor_name = str(root_snapshot.get('supervisor_name') or 'AI 分身')
        task_title = str(
            snapshot.get('supervisor_task_title')
            or task.get('title')
            or child.node_key
        )
        conversation = Conversation.objects.create(
            user_id=child.owner_id,
            organization_id=child.organization_id,
            title=f'{supervisor_name} · {task_title}'[:200],
            agent_id=agent_id,
            process_id=f"supervisor:{snapshot.get('supervisor_task_key') or child.node_key}"[:64],
            working_directory=str((child.input or {}).get('working_directory') or ''),
        )
        Conversation.objects.filter(pk=conversation.pk).update(
            created_at=child.created_at,
            updated_at=child.finished_at or child.created_at,
        )
        instructions = str(
            task.get('instructions')
            or (child.input or {}).get('message')
            or task_title
        )
        user_message = Message.objects.create(
            conversation=conversation,
            run=child,
            role='user',
            content=instructions,
            metadata={
                'run_id': str(child.id),
                'supervisor_root_run_id': str(child.parent_id or ''),
                'supervisor_task_key': (
                    snapshot.get('supervisor_task_key') or child.node_key
                ),
                'automated': True,
            },
        )
        Message.objects.filter(pk=user_message.pk).update(created_at=child.created_at)
        output = child.output_summary or {}
        result = output.get('result')
        if result not in (None, ''):
            message = Message.objects.create(
                conversation=conversation,
                run=child,
                run_event_sequence=child.next_event_sequence,
                role='assistant',
                content=str(result),
                metadata={
                    'run_id': str(child.id),
                    'run_event_sequence': child.next_event_sequence,
                    'model': output.get('model') or '',
                    'usage': output.get('usage') or {},
                },
            )
            Message.objects.filter(pk=message.pk).update(
                created_at=child.finished_at or child.created_at,
            )
        agent_thread = output.get('agent_thread') or {}
        provider = str(agent_thread.get('provider') or '')
        thread_id = str(agent_thread.get('id') or '')
        if provider and thread_id:
            Conversation.objects.filter(pk=conversation.pk).update(
                agent_thread_provider=provider,
                agent_thread_id=thread_id,
            )
        snapshot['conversation_id'] = str(conversation.id)
        snapshot['supervisor_root_conversation_id'] = root_snapshot.get(
            'conversation_id'
        )
        Run.objects.filter(pk=child.pk).update(definition_snapshot=snapshot)


class Migration(migrations.Migration):
    dependencies = [
        ('conversations', '0010_clear_implicit_general_agent'),
        ('execution', '0002_postgresql_rls'),
    ]

    operations = [
        migrations.RunPython(
            backfill_supervisor_agent_conversations,
            migrations.RunPython.noop,
        ),
    ]

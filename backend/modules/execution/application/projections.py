"""Project terminal Runs into domain read models without creating another executor."""
from django.db import transaction

from modules.execution.models import Run


def project_terminal_run(run_id, output):
    run = Run.objects.get(pk=run_id)
    if run.source_type != "conversation" or not run.source_id:
        return
    from apps.conversations.models import Conversation, Message

    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().filter(
            pk=run.source_id,
            organization_id=run.organization_id,
            user_id=run.owner_id,
        ).first()
        if conversation is None:
            return
        Message.objects.get_or_create(
            run=run,
            defaults={
                "conversation": conversation,
                "role": "assistant",
                "content": str(output.get("result") or ""),
                "metadata": {
                    "run_id": str(run.id),
                    "model": output.get("model") or "",
                    "usage": output.get("usage") or {},
                },
            },
        )

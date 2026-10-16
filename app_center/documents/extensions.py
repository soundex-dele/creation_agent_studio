"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    document_id = (run.input or {}).get('document_id')
    if not document_id:
        return None
    if not user.is_authenticated or run.owner_id != user.id:
        return False
    from django.http import Http404
    from django.core.exceptions import ValidationError
    from rest_framework.exceptions import APIException
    from .backend.models import Document
    from .backend.access import document_for
    try:
        document = Document.objects.filter(pk=document_id).first()
        if document is None:
            return False
        document_for(user, run.organization_id, document.application_id, document.pk)
    except (Http404, APIException, ValueError, ValidationError):
        return False
    return True


def conversation_access(conversation, user):
    from .backend.access import check_conversation_access
    return check_conversation_access(conversation, user)


def conversation_queryset(queryset):
    return queryset.filter(document_session__isnull=True)


def prepare_conversation_message(conversation, user, message, context):
    from .backend.access import prepare_document_message
    return prepare_document_message(conversation, user, message, context)


provider = ApplicationContributions(run_access=run_access, conversation_access=conversation_access, conversation_queryset=conversation_queryset, prepare_conversation_message=prepare_conversation_message, run_access_input_keys=('document_id',))

"""Supported integration API; callers retain permission and transaction contracts."""


_EXPORTS = {'Document': 'app_center.documents.backend.models',
 'DocumentSerializer': 'app_center.documents.backend.serializers',
 'application_for': 'app_center.documents.backend.access',
 'document_for': 'app_center.documents.backend.access',
 'plain_text': 'app_center.documents.backend.content',
 'validate_content': 'app_center.documents.backend.content',
 'visible_documents': 'app_center.documents.backend.access'}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(_EXPORTS[name]), name)

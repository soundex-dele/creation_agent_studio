"""Supported integration API; callers retain permission and transaction contracts."""


_EXPORTS = {'AnimationProject': 'app_center.animation_studio.backend.models',
 'document_assets': 'app_center.animation_studio.backend.projects',
 'empty_document': 'app_center.animation_studio.backend.documents',
 'validate_document': 'app_center.animation_studio.backend.documents'}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(_EXPORTS[name]), name)

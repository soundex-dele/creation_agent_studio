"""Supported integration API; callers retain permission and transaction contracts."""


_EXPORTS = {'IdeaSerializer': 'app_center.ideas_todos.backend.serializers',
 'TodoSerializer': 'app_center.ideas_todos.backend.serializers'}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(_EXPORTS[name]), name)

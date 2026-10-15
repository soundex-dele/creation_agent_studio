"""Supported conversation_execution capability for trusted application packages."""


_EXPORTS = {'ConversationRunActive': ('apps.conversations.execution', 'ConversationRunActive'),
 'create_conversation_run': ('apps.conversations.execution', 'create_conversation_run'),
 'ensure_supervisor_access': ('apps.conversations.execution', 'ensure_supervisor_access'),
 'resolve_agent': ('apps.conversations.execution', 'resolve_agent')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

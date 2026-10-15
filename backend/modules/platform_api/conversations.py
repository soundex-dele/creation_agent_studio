"""Supported conversations capability for trusted application packages."""


_EXPORTS = {'Conversation': ('apps.conversations.models', 'Conversation'),
 'ConversationDetailSerializer': ('apps.conversations.serializers', 'ConversationDetailSerializer'),
 'ConversationListSerializer': ('apps.conversations.serializers', 'ConversationListSerializer'),
 'Message': ('apps.conversations.models', 'Message'),
 'attach_existing_image': ('apps.conversations.services', 'attach_existing_image')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

"""Supported governance capability for trusted application packages."""


_EXPORTS = {'enforce_member_token_quota': ('apps.enterprise.services', 'enforce_member_token_quota'),
 'record_usage': ('apps.enterprise.services', 'record_usage'),
 'resolve_secret': ('apps.enterprise.services', 'resolve_secret')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

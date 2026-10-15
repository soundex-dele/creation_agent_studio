"""Supported storage capability for trusted application packages."""


_EXPORTS = {'signed_media_url': ('core.storage', 'signed_media_url')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

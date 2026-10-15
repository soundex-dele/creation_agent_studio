"""Public observability capability; implementation remains platform-owned."""

_EXPORTS = {'log_operation': ('core.observability', 'log_operation')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

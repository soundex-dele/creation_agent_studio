"""Supported runtime_paths capability for trusted application packages."""


_EXPORTS = {'resolve_runtime_path': ('apps.applications.runtime_paths', 'resolve_runtime_path'),
 'runtime_parent': ('apps.applications.runtime_paths', 'runtime_parent'),
 'runtime_path_is_accessible': ('apps.applications.runtime_paths', 'runtime_path_is_accessible'),
 'visible_runtime_roots': ('apps.applications.runtime_paths', 'visible_runtime_roots')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

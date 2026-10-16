"""Public identity capability; implementation remains platform-owned."""


_EXPORTS = {'Application': ('apps.applications.models', 'Application'),
 'Membership': ('apps.enterprise.models', 'Membership'),
 'Organization': ('apps.enterprise.models', 'Organization'),
 'QuotaPolicy': ('apps.enterprise.models', 'QuotaPolicy'),
 'accessible_resources': ('core.resource_access', 'accessible_resources'),
 'active_member_applications': ('core.resource_access', 'active_member_applications'),
 'can_access_resource': ('core.resource_access', 'can_access_resource'),
 'resolve_organization': ('apps.enterprise.permissions', 'resolve_organization')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

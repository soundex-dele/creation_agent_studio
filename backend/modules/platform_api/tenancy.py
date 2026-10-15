"""Public tenancy capability; implementation remains platform-owned."""


_EXPORTS = {'HasPathOrganization': ('modules.tenancy.permissions', 'HasPathOrganization'),
 'HasPathOrganizationRole': ('modules.tenancy.permissions', 'HasPathOrganizationRole'),
 'ROLE_LEVEL': ('modules.tenancy.permissions', 'ROLE_LEVEL'),
 'TenantOwnedModel': ('modules.tenancy.models', 'TenantOwnedModel'),
 'TenantOwnedQuerySet': ('modules.tenancy.models', 'TenantOwnedQuerySet'),
 'resolve_path_organization': ('modules.tenancy.permissions', 'resolve_path_organization'),
 'tenant_database_context': ('modules.tenancy.database', 'tenant_database_context')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

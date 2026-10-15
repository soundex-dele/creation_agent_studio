"""Public cases capability; implementation remains platform-owned."""

_EXPORTS = {'Template': ('apps.templates.models', 'Template'),
 'TemplateAnalysisSection': ('apps.templates.models', 'TemplateAnalysisSection'),
 'TemplateCategory': ('apps.templates.models', 'TemplateCategory'),
 'visible_cases': ('apps.templates.access', 'visible_cases')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

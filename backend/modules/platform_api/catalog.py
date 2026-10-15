"""Supported catalog capability for trusted application packages."""


_EXPORTS = {'AgentDeployment': ('modules.catalog.models', 'AgentDeployment'),
 'AgentDraft': ('modules.catalog.models', 'AgentDraft'),
 'compose_guided_prompt': ('modules.catalog.guided_prompts', 'compose_guided_prompt'),
 'publish_agent': ('modules.catalog.services', 'publish_agent'),
 'switch_agent_deployment': ('modules.catalog.services', 'switch_agent_deployment')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

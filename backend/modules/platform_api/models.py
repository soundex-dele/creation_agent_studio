"""Public models capability; implementation remains platform-owned."""


_EXPORTS = {'CodexAdapter': ('core.agent_engine.adapters.codex', 'CodexAdapter'),
 'GenerationError': ('core.llm.application', 'GenerationError'),
 'build_agent_engine': ('core.llm.factory', 'build_agent_engine'),
 'engine_failure': ('core.llm.application', 'engine_failure'),
 'generate_json': ('core.llm.application', 'generate_json')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

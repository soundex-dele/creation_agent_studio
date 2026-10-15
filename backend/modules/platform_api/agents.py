"""Supported agents capability for trusted application packages."""


_EXPORTS = {'Agent': ('apps.agents.models', 'Agent'),
 'AgentCategory': ('apps.agents.models', 'AgentCategory'),
 'TUTOR_DEFINITIONS': ('apps.agents.high_school_tutors', 'TUTOR_DEFINITIONS'),
 'TUTOR_DEFINITION_BY_SUBJECT': ('apps.agents.high_school_tutors', 'TUTOR_DEFINITION_BY_SUBJECT')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

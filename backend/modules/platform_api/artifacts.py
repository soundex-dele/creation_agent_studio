"""Artifacts use the existing platform object store and execution records."""


_EXPORTS = {'ArtifactObjectUnavailable': ('modules.execution.infrastructure.artifacts',
                               'ArtifactObjectUnavailable'),
 'delete_artifact_object': ('modules.execution.infrastructure.artifacts', 'delete_artifact_object'),
 'get_artifact_storage': ('modules.execution.infrastructure.artifacts', 'get_artifact_storage'),
 'open_artifact': ('modules.execution.infrastructure.artifacts', 'open_artifact'),
 'persist_artifact': ('modules.execution.infrastructure.artifacts', 'persist_artifact'),
 'record_artifact': ('modules.execution.application.runs', 'record_artifact'),
 'workspace_file': ('apps.workflows.artifacts', 'workspace_file')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

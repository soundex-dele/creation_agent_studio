"""Public knowledge capability; implementation remains platform-owned."""


_EXPORTS = {'KnowledgeBase': ('apps.knowledge.models', 'KnowledgeBase'),
 'KnowledgeChunk': ('apps.knowledge.models', 'KnowledgeChunk'),
 'KnowledgeDocument': ('apps.knowledge.models', 'KnowledgeDocument'),
 'create_document': ('apps.knowledge.services', 'create_document'),
 'delete_document_index': ('apps.knowledge.index_backend', 'delete_document_index'),
 'embed_texts': ('apps.knowledge.providers', 'embed_texts'),
 'reindex_document': ('apps.knowledge.services', 'reindex_document'),
 'search': ('apps.knowledge.retrieval', 'search'),
 'serialize_result': ('apps.knowledge.retrieval', 'serialize_result')}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module), attribute)

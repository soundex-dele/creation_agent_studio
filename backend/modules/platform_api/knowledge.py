"""Public knowledge capability; implementation remains platform-owned."""
from apps.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from apps.knowledge.retrieval import search, serialize_result
from apps.knowledge.services import reindex_document
